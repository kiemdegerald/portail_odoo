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


class GmIndemniteType(models.Model):
    """Les postes qui composent l'indemnité de mission : restauration,
    hébergement, transport... La banque définit sa propre liste.

    Elle peut n'en créer qu'UN, dans lequel elle met tout : on retombe
    alors exactement sur le fonctionnement d'origine, une indemnité
    journalière unique. C'est ce qui rend ce découpage sans risque —
    c'est la banque qui décide si elle découpe, et jusqu'où.
    """
    _name = "gm.indemnite.type"
    _description = "Type d'indemnité de mission"
    _order = "sequence, id"

    name = fields.Char(string="Type d'indemnité", required=True)
    sequence = fields.Integer(
        string="Ordre", default=10,
        help="Ordre d'affichage, et ordre des colonnes sur la fiche de "
             "décompte.")
    company_id = fields.Many2one(
        "res.company", string="Société",
        help="Vide = commun à toutes les sociétés.")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("name_company_uniq", "unique(name, company_id)",
         "Ce type d'indemnité existe déjà."),
    ]


class GmPerdiemRate(models.Model):
    """Barème des indemnités journalières : zone de mission × catégorie
    d'agent × TYPE d'indemnité -> montant par jour. Configurable par les
    RH (Missions > Configuration > Barème des indemnités).

    Une ligne par croisement : « un cadre moyen en mission nationale
    touche tant de restauration et tant d'hébergement, par jour ». Pas de
    ligne, pas de droit.
    """
    _name = "gm.perdiem.rate"
    _description = "Barème d'indemnité journalière de mission"
    _order = "zone_id, categorie, type_id"

    zone_id = fields.Many2one(
        "gm.mission.zone", string="Zone", required=True,
        ondelete="restrict")
    categorie = fields.Selection(
        selection=lambda self: get_categorie_selection(self.env),
        string="Catégorie d'agent", required=True,
        help="Catégorie issue de la grille salariale (classification de "
             "l'employé).")
    type_id = fields.Many2one(
        "gm.indemnite.type", string="Type d'indemnité",
        ondelete="restrict", index=True,
        help="Poste d'indemnité concerné. Une ligne par poste : c'est ce "
             "qui permet de dire séparément la restauration et "
             "l'hébergement.")
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
        ("zoneid_categorie_type_company_uniq",
         "unique(zone_id, categorie, type_id, company_id)",
         "Un barème existe déjà pour cette zone, cette catégorie et ce "
         "type d'indemnité."),
    ]

    @api.constrains("montant_jour")
    def _check_montant(self):
        for rate in self:
            if rate.montant_jour <= 0:
                raise ValidationError(_(
                    "Le montant journalier doit être positif."))

    @api.model
    def get_rates(self, zone, categorie, company):
        """TOUTES les lignes de barème applicables : une par type.

        Une ligne propre à la société l'emporte sur la ligne commune du
        même type — la règle d'origine, appliquée type par type.
        """
        lignes = self.search([
            ("zone_id", "=", zone.id),
            ("categorie", "=", categorie),
            ("company_id", "in", [company.id, False]),
        ], order="company_id desc")
        retenues = {}
        for ligne in lignes:
            retenues.setdefault(ligne.type_id.id, ligne)
        return self.browse([l.id for l in retenues.values()]).sorted(
            lambda l: (l.type_id.sequence, l.type_id.id))
