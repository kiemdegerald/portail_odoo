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
    # Un chauffeur n'a pas de fiche employé : sans cela, il s'affichait
    # « Sans nom » dans les listes déroulantes (frais, indemnités).
    _rec_name = "nom_affiche"

    mission_id = fields.Many2one(
        "gm.mission", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(default=10)
    # Un missionnaire est SOIT un agent de la banque, SOIT un chauffeur du
    # répertoire. Le chauffeur n'a ni classification ni barème : ses
    # indemnités se saisissent à la main.
    employee_id = fields.Many2one(
        "hr.employee", string="Membre", ondelete="restrict")
    chauffeur_id = fields.Many2one(
        "gm.chauffeur", string="Chauffeur", ondelete="restrict",
        help="Pour un chauffeur du répertoire, qui n'a pas de fiche "
             "employé ni de barème.")
    # DEUX calculs séparés, et c'est volontaire. Réunis dans une seule
    # méthode, le nom restait vide : la fonction étant modifiable, le
    # formulaire l'envoie à l'enregistrement, ce qui neutralise le calcul
    # partagé — et le nom avec. Un membre chauffeur s'affichait alors
    # « Sans nom » dans les listes déroulantes.
    nom_affiche = fields.Char(
        string="Nom", compute="_compute_nom_affiche", store=True)
    job_title = fields.Char(
        string="Fonction", compute="_compute_job_title", store=True,
        readonly=False)
    compte_bancaire = fields.Char(
        string="N° de compte", compute="_compute_compte_bancaire",
        help="Compte crédité par la fiche d'imputation.")

    @api.depends("employee_id", "chauffeur_id",
                 "employee_id.name", "chauffeur_id.name")
    def _compute_nom_affiche(self):
        for membre in self:
            membre.nom_affiche = (membre.employee_id.name
                                  or membre.chauffeur_id.name
                                  or False)

    @api.depends("employee_id", "chauffeur_id")
    def _compute_job_title(self):
        for membre in self:
            membre.job_title = (membre.employee_id.job_title
                                or membre.chauffeur_id.fonction
                                or False)

    @api.depends("employee_id", "chauffeur_id")
    def _compute_compte_bancaire(self):
        for membre in self:
            if membre.employee_id:
                membre.compte_bancaire = membre.employee_id.sudo(
                ).bank_account_id.acc_number or False
            else:
                membre.compte_bancaire =                     membre.chauffeur_id.compte_effectif or False

    @api.constrains("employee_id", "chauffeur_id")
    def _check_identite(self):
        """Un missionnaire, une identité : ni les deux, ni aucune."""
        for membre in self:
            if membre.employee_id and membre.chauffeur_id:
                raise ValidationError(_(
                    "Une ligne désigne soit un agent, soit un chauffeur — "
                    "pas les deux. Videz l'un des deux champs."))
            if not membre.employee_id and not membre.chauffeur_id:
                raise ValidationError(_(
                    "Chaque ligne doit désigner quelqu'un : un agent de la "
                    "banque, ou un chauffeur du répertoire."))
    is_chef = fields.Boolean(
        string="Chef", compute="_compute_is_chef",
        help="Chef de mission = le demandeur de la fiche (ancre du "
             "circuit de validation).")

    @api.depends("employee_id", "mission_id.employee_id")
    def _compute_is_chef(self):
        for membre in self:
            membre.is_chef = (membre.employee_id
                              == membre.mission_id.employee_id)
    currency_id = fields.Many2one(
        # STOCKÉE : au moment d'écrire un champ monétaire, Odoo relit
        # sa devise. Non stockée, elle était relue sur la mission —
        # déjà effacée pendant une suppression en cascade, d'où
        # « Enregistrement inexistant ou supprimé ».
        related="mission_id.currency_id", store=True)

    # --- Photo financière du membre (figée à la soumission) ---
    categorie_agent = fields.Char(
        string="Catégorie", readonly=True, copy=False)
    indemnite_jour = fields.Monetary(
        string="Indemnité / jour", readonly=True, copy=False)
    indemnite_ids = fields.One2many(
        "gm.mission.indemnite", "membre_id", string="Détail des indemnités",
        copy=False,
        help="Une ligne par type d'indemnité, générée à la soumission "
             "depuis le barème.")
    indemnite_total = fields.Monetary(
        string="Indemnité", compute="_compute_indemnite_total", store=True,
        readonly=True, copy=False,
        help="Somme des indemnités du missionnaire, tous types confondus.")

    @api.depends("indemnite_ids.montant")
    def _compute_indemnite_total(self):
        for membre in self:
            membre.indemnite_total = sum(membre.indemnite_ids.mapped("montant"))
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
        # gm_suppression_mission : c'est la mission ENTIÈRE qui est
        # supprimée ; ses lignes partent avec elle, quel que soit son
        # état. Le droit de supprimer la mission a déjà été vérifié.
        if (self.env.context.get("gm_migration")
                or self.env.context.get("gm_recompute")
                or self.env.context.get("gm_suppression_mission")):
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
