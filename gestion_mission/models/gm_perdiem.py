# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

# Catégories de repli si la grille salariale (modèle Studio
# x_grille_salariale) n'existe pas sur la base (portabilité : autre client).
FALLBACK_CATEGORIES = [
    ("Agent d'execution", "Agent d'exécution"),
    ("Cadre moyen", "Cadre moyen"),
    ("Cadre supérieur", "Cadre supérieur"),
]


def get_categorie_selection(env):
    """Les catégories d'agent, lues DYNAMIQUEMENT depuis la grille
    salariale de la base (champ Studio ``x_grille_salariale.x_studio_catgorie``).
    Si la banque ajoute une catégorie à sa grille, elle apparaît ici sans
    redéploiement. Repli sur une liste standard si la grille n'existe pas.
    """
    field = env["ir.model.fields"].sudo().search([
        ("model", "=", "x_grille_salariale"),
        ("name", "=", "x_studio_catgorie"),
    ], limit=1)
    if field and field.selection_ids:
        return [(s.value, s.name or s.value) for s in field.selection_ids]
    return FALLBACK_CATEGORIES


class GmMissionZone(models.Model):
    """Zones de mission (référentiel configurable par les RH) : elles
    déterminent, avec la catégorie d'agent, le barème d'indemnité
    applicable. La banque définit son propre découpage (Missions >
    Configuration > Zones de mission)."""
    _name = "gm.mission.zone"
    _description = "Zone de mission"
    _order = "sequence, id"

    name = fields.Char(string="Zone", required=True)
    sequence = fields.Integer(string="Ordre", default=10)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("name_uniq", "unique(name)", "Cette zone existe déjà."),
    ]


class GmPerdiemRate(models.Model):
    """Barème des indemnités journalières : zone de mission × catégorie
    d'agent -> montant par jour. Configurable par les RH (Missions >
    Configuration > Barème des indemnités)."""
    _name = "gm.perdiem.rate"
    _description = "Barème d'indemnité journalière de mission"
    _order = "zone_id, categorie"

    zone_id = fields.Many2one(
        "gm.mission.zone", string="Zone", required=True,
        ondelete="restrict")
    categorie = fields.Selection(
        selection=lambda self: get_categorie_selection(self.env),
        string="Catégorie d'agent", required=True,
        help="Catégorie issue de la grille salariale (classification de "
             "l'employé).")
    montant_jour = fields.Monetary(
        string="Indemnité / jour", required=True,
        currency_field="currency_id")
    currency_id = fields.Many2one(
        "res.currency", string="Devise",
        default=lambda self: self.env.company.currency_id, required=True)
    company_id = fields.Many2one(
        "res.company", string="Société",
        help="Vide = barème commun à toutes les sociétés.")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("zoneid_categorie_company_uniq",
         "unique(zone_id, categorie, company_id)",
         "Un barème existe déjà pour cette zone et cette catégorie."),
    ]

    @api.constrains("montant_jour")
    def _check_montant(self):
        for rate in self:
            if rate.montant_jour <= 0:
                raise ValidationError(_(
                    "Le montant journalier doit être positif."))

    @api.model
    def get_rate(self, zone, categorie, company):
        """Barème applicable : celui de la société, sinon le commun."""
        rate = self.search([
            ("zone_id", "=", zone.id),
            ("categorie", "=", categorie),
            ("company_id", "in", [company.id, False]),
        ], order="company_id desc", limit=1)
        return rate
