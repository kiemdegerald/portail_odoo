# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class GmMissionFrais(models.Model):
    """Lignes « Autres frais (à justifier) » d'une mission : plusieurs
    postes possibles, chacun avec sa description (cf. fiche de décompte
    réelle). Le total alimente le champ calculé ``autres_frais`` de la
    mission, donc le total dû et l'avance."""
    _name = "gm.mission.frais"
    _description = "Autres frais d'une mission"
    _order = "id"

    mission_id = fields.Many2one(
        "gm.mission", required=True, ondelete="cascade", index=True)
    membre_id = fields.Many2one(
        "gm.mission.membre", string="Membre", ondelete="cascade", index=True,
        help="Missionnaire concerné par ce frais (cf. fiche de décompte "
             "par missionnaire). Laissé vide : rattaché automatiquement "
             "au chef de mission à la soumission.")
    description = fields.Char(
        string="Description", required=True,
        help="Nature du frais : billet d'avion, frais de visa, "
             "inscription à la formation...")
    montant = fields.Monetary(
        string="Montant", required=True, currency_field="currency_id")
    currency_id = fields.Many2one(
        related="mission_id.currency_id")

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
    # Verrou : plus aucune modification une fois l'avance versée
    # (les montants ont été décaissés sur cette base).
    # ------------------------------------------------------------------
    def _check_mission_locked(self, missions):
        if self.env.context.get("gm_migration"):
            return
        for mission in missions:
            if mission.avance_versee:
                raise UserError(_(
                    "L'avance de la mission %s a déjà été versée : les "
                    "autres frais ne peuvent plus être modifiés.",
                    mission.name))

    @api.model_create_multi
    def create(self, vals_list):
        missions = self.env["gm.mission"].browse(
            [v["mission_id"] for v in vals_list if v.get("mission_id")])
        self._check_mission_locked(missions)
        return super().create(vals_list)

    def write(self, vals):
        self._check_mission_locked(self.mapped("mission_id"))
        return super().write(vals)

    def unlink(self):
        self._check_mission_locked(self.mapped("mission_id"))
        return super().unlink()
