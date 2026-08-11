# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GmMissionMembre(models.Model):
    """Membres d'une mission (cf. tableau « Membres de la mission » de
    l'ordre de mission réel) : chaque membre porte SA photo financière,
    prise à la soumission — sa catégorie détermine son taux journalier.
    Les montants de la mission sont les sommes des membres."""
    _name = "gm.mission.membre"
    _description = "Membre d'une mission"
    _order = "sequence, id"
    _rec_name = "employee_id"

    mission_id = fields.Many2one(
        "gm.mission", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    employee_id = fields.Many2one(
        "hr.employee", string="Membre", required=True, ondelete="restrict")
    job_title = fields.Char(
        related="employee_id.job_title", string="Fonction")
    is_chef = fields.Boolean(
        string="Chef", compute="_compute_is_chef",
        help="Chef de mission = le demandeur de la fiche (ancre du "
             "circuit de validation).")

    @api.depends("employee_id", "mission_id.employee_id")
    def _compute_is_chef(self):
        for membre in self:
            membre.is_chef = (membre.employee_id
                              == membre.mission_id.employee_id)
    currency_id = fields.Many2one(related="mission_id.currency_id")

    # --- Photo financière du membre (figée à la soumission) ---
    categorie_agent = fields.Char(
        string="Catégorie", readonly=True, copy=False)
    indemnite_jour = fields.Monetary(
        string="Indemnité / jour", readonly=True, copy=False)
    indemnite_total = fields.Monetary(
        string="Indemnité", readonly=True, copy=False)
    frais_ids = fields.One2many(
        "gm.mission.frais", "membre_id", string="Frais du membre")
    autres_frais = fields.Monetary(
        string="Autres frais", compute="_compute_autres_frais", store=True,
        help="Frais PRÉVUS avant le retour, frais RÉELS déclarés à partir "
             "du retour (décompte définitif).")
    total_du = fields.Monetary(
        string="Total dû", compute="_compute_total_du", store=True)
    avance_montant = fields.Monetary(
        string="Avance", copy=False,
        help="Part d'avance du membre, proposée à la soumission "
             "(% paramétrable), ajustable par le gestionnaire jusqu'au "
             "versement.")
    solde = fields.Monetary(
        string="Solde", compute="_compute_total_du", store=True)

    _sql_constraints = [
        ("membre_unique", "unique(mission_id, employee_id)",
         "Cet agent est déjà membre de la mission : il ne peut y figurer "
         "qu'une seule fois."),
    ]

    @api.depends("frais_ids.montant", "frais_ids.type_frais",
                 "mission_id.state")
    def _compute_autres_frais(self):
        for membre in self:
            membre.autres_frais = sum(
                membre.frais_ids.filtered(
                    lambda f: f.type_frais == membre.mission_id._frais_actifs()
                ).mapped("montant"))

    @api.depends("indemnite_total", "autres_frais", "avance_montant")
    def _compute_total_du(self):
        for membre in self:
            membre.total_du = membre.indemnite_total + membre.autres_frais
            membre.solde = membre.total_du - membre.avance_montant

    # ------------------------------------------------------------------
    # Verrou : plus de modification une fois l'avance versée
    # (même règle que les lignes de frais).
    # ------------------------------------------------------------------
    def _check_mission_locked(self, missions):
        # gm_migration : reprise de données ; gm_recompute : recalcul
        # système des indemnités au retour de mission (l'avance est alors
        # déjà versée, mais le décompte définitif doit pouvoir s'écrire).
        if (self.env.context.get("gm_migration")
                or self.env.context.get("gm_recompute")):
            return
        for mission in missions:
            # États terminaux : le décompte est arrêté, plus rien ne bouge —
            # même règle que les lignes de frais (cf. gm_frais.py). Sans ce
            # contrôle, un gestionnaire pouvait encore modifier l'avance d'un
            # membre sur une mission CLÔTURÉE dès lors que « Avance versée »
            # n'était pas cochée, ce qui changeait le solde après clôture.
            if mission.state in ("closed", "cancelled"):
                raise UserError(_(
                    "La mission %s est %s : ses membres et leurs montants ne "
                    "sont plus modifiables.", mission.name,
                    _("clôturée") if mission.state == "closed"
                    else _("annulée")))
            if mission.avance_versee:
                raise UserError(_(
                    "L'avance de la mission %s a déjà été versée : les "
                    "membres ne peuvent plus être modifiés.", mission.name))

    @api.model_create_multi
    def create(self, vals_list):
        missions = self.env["gm.mission"].browse(
            [v["mission_id"] for v in vals_list if v.get("mission_id")])
        self._check_mission_locked(missions)
        return super().create(vals_list)

    def write(self, vals):
        # la photo (écrite par la soumission) et la remise à zéro (retour
        # en brouillon) passent par sudo métier avec avance non versée ;
        # ici on ne verrouille que le cas avance déjà décaissée.
        self._check_mission_locked(self.mapped("mission_id"))
        return super().write(vals)

    def unlink(self):
        self._check_mission_locked(self.mapped("mission_id"))
        return super().unlink()
