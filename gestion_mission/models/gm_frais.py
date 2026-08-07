# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GmMissionFrais(models.Model):
    """Lignes « Autres frais (à justifier) » d'une mission.

    Deux natures, conservées CÔTE À CÔTE (piste d'audit) :
    * ``prevu`` — saisi à la demande, sert au calcul de l'avance ;
    * ``reel`` — déclaré au retour (note de frais), justificatif à
      l'appui ; c'est lui qui fait le décompte définitif.
    Le total actif (``autres_frais`` de la mission et du membre) suit
    l'état : prévu avant le retour, réel à partir du retour déclaré.
    """
    _name = "gm.mission.frais"
    _description = "Autres frais d'une mission"
    _order = "type_frais, id"

    mission_id = fields.Many2one(
        "gm.mission", required=True, ondelete="cascade", index=True)
    membre_id = fields.Many2one(
        "gm.mission.membre", string="Membre", ondelete="cascade", index=True,
        help="Missionnaire concerné par ce frais (cf. fiche de décompte "
             "par missionnaire). Laissé vide : rattaché automatiquement "
             "au chef de mission à la soumission.")
    type_frais = fields.Selection([
        ("prevu", "Prévu"),
        ("reel", "Réel (au retour)"),
    ], string="Nature", default="prevu", required=True, index=True)
    description = fields.Char(
        string="Description", required=True,
        help="Nature du frais : billet d'avion, frais de visa, "
             "inscription à la formation...")
    montant = fields.Monetary(
        string="Montant", required=True, currency_field="currency_id")
    currency_id = fields.Many2one(
        related="mission_id.currency_id")
    justificatif = fields.Binary(
        string="Justificatif", attachment=True,
        help="Facture, reçu, billet... Exigé sur les frais réels pour "
             "pouvoir clôturer la mission.")
    justificatif_filename = fields.Char(string="Nom du fichier")

    @api.constrains("montant")
    def _check_montant(self):
        for line in self:
            if line.montant <= 0:
                raise ValidationError(_(
                    "Le montant d'un frais doit être positif."))

    @api.constrains("membre_id", "mission_id")
    def _check_membre_mission(self):
        for line in self:
            if line.membre_id and line.membre_id.mission_id != line.mission_id:
                raise ValidationError(_(
                    "Le membre du frais doit appartenir à la même mission."))

    # ------------------------------------------------------------------
    # Verrous : les frais PRÉVUS se figent au versement de l'avance
    # (ils en sont la base) ; les frais RÉELS ne vivent qu'entre le
    # retour déclaré et la clôture.
    # ------------------------------------------------------------------
    def _check_line_locked(self, lines_data):
        """lines_data : liste de tuples (mission, type_frais)."""
        if (self.env.context.get("gm_migration")
                or self.env.context.get("gm_recompute")):
            return
        for mission, type_frais in lines_data:
            if mission.state in ("closed", "cancelled"):
                raise UserError(_(
                    "La mission %s est %s : ses frais ne sont plus "
                    "modifiables.", mission.name,
                    _("clôturée") if mission.state == "closed"
                    else _("annulée")))
            if type_frais == "reel":
                if mission.state != "returned":
                    raise UserError(_(
                        "Les frais réels se déclarent au moment du retour "
                        "de mission (mission %s).", mission.name))
            elif mission.state == "returned":
                # Le retour est déclaré : le prévisionnel est archivé tel
                # quel (base de comparaison) ; seuls les frais RÉELS
                # bougent encore.
                raise UserError(_(
                    "Le retour de la mission %s est déclaré : les frais "
                    "prévus sont figés. Corrigez les frais RÉELS (note de "
                    "frais).", mission.name))
            elif mission.avance_versee:
                raise UserError(_(
                    "L'avance de la mission %s a déjà été versée : les "
                    "frais prévus ne peuvent plus être modifiés.",
                    mission.name))

    @api.model_create_multi
    def create(self, vals_list):
        Mission = self.env["gm.mission"]
        self._check_line_locked([
            (Mission.browse(v["mission_id"]), v.get("type_frais", "prevu"))
            for v in vals_list if v.get("mission_id")])
        return super().create(vals_list)

    def write(self, vals):
        self._check_line_locked([(l.mission_id, l.type_frais) for l in self])
        # Traçabilité : un ajustement de montant sur un frais réel par le
        # gestionnaire est consigné au dossier (exigence de contrôle).
        if "montant" in vals:
            for line in self.filtered(
                    lambda l: l.type_frais == "reel"
                    and l.mission_id.state == "returned"
                    and l.montant != vals["montant"]):
                line.mission_id.message_post(body=_(
                    "Frais réel « %(desc)s » ajusté par %(user)s : "
                    "%(avant)s -> %(apres)s.",
                    desc=line.description, user=self.env.user.name,
                    avant=line.montant, apres=vals["montant"]))
        return super().write(vals)

    def unlink(self):
        self._check_line_locked([(l.mission_id, l.type_frais) for l in self])
        return super().unlink()
