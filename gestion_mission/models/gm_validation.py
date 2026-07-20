# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class GmValidationStep(models.Model):
    """CONFIGURATION du circuit de validation (écran RH).

    Liste ordonnée des niveaux. À la soumission d'une mission, ces étapes
    sont PHOTOGRAPHIÉES sur la mission (gm.mission.validation) : modifier
    la configuration ensuite n'affecte jamais les missions déjà en route.
    """
    _name = "gm.validation.step"
    _description = "Niveau de validation des missions (configuration)"
    _order = "sequence, id"

    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(
        string="Niveau", required=True,
        help="Ex. : Supérieur hiérarchique, Direction, Service financier...")
    validator_type = fields.Selection([
        ("manager", "Le supérieur hiérarchique du demandeur"),
        ("fixed", "Une personne désignée"),
    ], string="Qui valide", required=True, default="manager",
        help="« Supérieur hiérarchique » = le champ Manager de la fiche "
             "employé du demandeur, résolu au moment de la soumission.")
    validator_id = fields.Many2one(
        "hr.employee", string="Personne désignée",
        help="Employé qui valide ce niveau (si « Une personne désignée »).")
    company_id = fields.Many2one(
        "res.company", string="Société",
        default=lambda self: self.env.company,
        help="Vide = niveau commun à toutes les sociétés.")
    active = fields.Boolean(default=True)

    @api.constrains("validator_type", "validator_id")
    def _check_validator(self):
        for step in self:
            if step.validator_type == "fixed" and not step.validator_id:
                raise ValidationError(_(
                    "Le niveau « %s » exige une personne désignée.",
                    step.name))


class GmMissionValidation(models.Model):
    """PHOTO du circuit sur une mission : une ligne par niveau, figée à la
    soumission. C'est la piste d'audit : qui devait valider, qui a agi,
    quand, avec quel commentaire — quelle que soit l'évolution ultérieure
    de la configuration. Écritures uniquement via les actions de gm.mission
    (jamais à la main)."""
    _name = "gm.mission.validation"
    _description = "Étape de validation d'une mission"
    _order = "sequence, id"

    mission_id = fields.Many2one(
        "gm.mission", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(string="Ordre")
    name = fields.Char(string="Niveau", required=True)
    validator_id = fields.Many2one(
        "hr.employee", string="Valideur attendu", required=True,
        help="Résolu au moment de la soumission (photo).")
    state = fields.Selection([
        ("waiting", "À venir"),
        ("pending", "En attente"),
        ("approved", "Approuvée"),
        ("refused", "Refusée"),
    ], string="Statut", default="waiting", required=True)
    acted_by_id = fields.Many2one(
        "res.users", string="Traitée par", readonly=True,
        help="Utilisateur qui a réellement agi (peut être un gestionnaire).")
    date_action = fields.Datetime(string="Le", readonly=True)
    comment = fields.Text(string="Commentaire")
