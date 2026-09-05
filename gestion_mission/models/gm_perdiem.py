# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


def poser_index_partiels(cr, table, index_avec, index_sans, colonnes,
                         colonne_nulle="company_id"):
    """Deux index uniques partiels : l'un quand la colonne est renseignée,
    l'autre quand elle est vide. Sans cela, deux lignes « toutes sociétés »
    ne sont jamais vues comme un doublon.

    Un doublon DÉJÀ présent en base ferait échouer la création de l'index :
    on trace un avertissement plutôt que de bloquer la mise à jour du
    module — la RH devra alors nettoyer.
    """
    sans = ", ".join(c for c in colonnes if c != colonne_nulle)
    for nom, sql in (
        (index_avec, "CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s (%s) "
                     "WHERE %s IS NOT NULL"
                     % (index_avec, table, ", ".join(colonnes), colonne_nulle)),
        (index_sans, "CREATE UNIQUE INDEX IF NOT EXISTS %s ON %s (%s) "
                     "WHERE %s IS NULL"
                     % (index_sans, table, sans, colonne_nulle)),
    ):
        try:
            with cr.savepoint():
                cr.execute(sql)
        except Exception as exc:            # doublon déjà en base
            _logger.warning(
                "Index d'unicité %s non créé (doublons existants ?) : %s",
                nom, exc)

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
    a_justifier = fields.Boolean(
        string="À justifier au retour", default=False,
        help="Cochée, cette indemnité doit être justifiée au retour de "
             "mission : le missionnaire produit une pièce (facture, reçu). "
             "Décochée, elle est forfaitaire — l'agent la garde, quoi "
             "qu'il ait dépensé. "
             "Le réglage est PHOTOGRAPHIÉ sur chaque mission au moment de "
             "la soumission : le modifier ensuite ne change rien aux "
             "missions déjà parties.")
    company_id = fields.Many2one(
        "res.company", string="Société",
        help="Vide = commun à toutes les sociétés.")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("name_company_uniq", "unique(name, company_id)",
         "Ce type d'indemnité existe déjà."),
    ]

    # PostgreSQL considère que deux NULL sont DIFFÉRENTS : la contrainte
    # ci-dessus ne voit donc jamais un doublon quand la société est vide —
    # or « vide = commun à toutes les sociétés » est l'usage recommandé.
    # D'où ces deux verrous : le contrôle Python donne le message lisible,
    # l'index partiel tient même pour un import ou un écrit direct.
    def _refuser_doublon(self, nom, societe, exclure=None):
        """Contrôle AVANT écriture. L'index part à l'insertion, donc avant
        tout contrôle Python : sans cela, l'utilisateur lit un message
        PostgreSQL brut au lieu d'une phrase."""
        domaine = [("name", "=ilike", nom or ""),
                   ("company_id", "=", societe or False)]
        if exclure:
            domaine = [("id", "!=", exclure)] + domaine
        if self.search_count(domaine):
            raise ValidationError(_(
                "Le type d'indemnité « %s » existe déjà.", nom))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._refuser_doublon(vals.get("name"), vals.get("company_id"))
        return super().create(vals_list)

    def write(self, vals):
        if "name" in vals or "company_id" in vals:
            for type_ind in self:
                self._refuser_doublon(
                    vals.get("name", type_ind.name),
                    vals.get("company_id", type_ind.company_id.id),
                    exclure=type_ind.id)
        return super().write(vals)

    def init(self):
        super().init()
        poser_index_partiels(
            self.env.cr, "gm_indemnite_type",
            "gm_indemnite_type_nom_societe_uniq",
            "gm_indemnite_type_nom_sans_societe_uniq",
            ["name", "company_id"])


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

    # PostgreSQL considère que deux NULL sont DIFFÉRENTS : la contrainte
    # ci-dessus ne voit donc jamais un doublon quand la société est vide —
    # or « vide = commun à toutes les sociétés » est l'usage recommandé.
    # D'où ces deux verrous : le contrôle Python donne le message lisible,
    # l'index partiel tient même pour un import ou un écrit direct.
    def _refuser_doublon(self, zone_id, categorie, type_id, societe,
                         exclure=None):
        domaine = [("zone_id", "=", zone_id or False),
                   ("categorie", "=", categorie),
                   ("type_id", "=", type_id or False),
                   ("company_id", "=", societe or False)]
        if exclure:
            domaine = [("id", "!=", exclure)] + domaine
        if self.search_count(domaine):
            zone = self.env["gm.mission.zone"].browse(zone_id)
            type_ind = self.env["gm.indemnite.type"].browse(type_id)
            raise ValidationError(_(
                "Un barème existe déjà pour « %(zone)s », la catégorie "
                "« %(cat)s » et le type « %(type)s ». Corrigez la ligne "
                "existante plutôt que d'en créer une seconde : le système "
                "n'en retiendrait qu'une, et pas forcément celle que vous "
                "venez de saisir.",
                zone=zone.name, cat=categorie, type=type_ind.name))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._refuser_doublon(vals.get("zone_id"), vals.get("categorie"),
                                  vals.get("type_id"), vals.get("company_id"))
        return super().create(vals_list)

    def write(self, vals):
        champs = ("zone_id", "categorie", "type_id", "company_id")
        if any(c in vals for c in champs):
            for ligne in self:
                self._refuser_doublon(
                    vals.get("zone_id", ligne.zone_id.id),
                    vals.get("categorie", ligne.categorie),
                    vals.get("type_id", ligne.type_id.id),
                    vals.get("company_id", ligne.company_id.id),
                    exclure=ligne.id)
        return super().write(vals)

    def init(self):
        super().init()
        poser_index_partiels(
            self.env.cr, "gm_perdiem_rate",
            "gm_perdiem_rate_croisement_societe_uniq",
            "gm_perdiem_rate_croisement_sans_societe_uniq",
            ["zone_id", "categorie", "type_id", "company_id"])

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
        ])
        # Le tri se fait en PYTHON, et c'est essentiel : sous PostgreSQL,
        # « ORDER BY company_id DESC » place les NULL en TÊTE. La ligne
        # COMMUNE passait donc devant la ligne propre à la société, et
        # c'est elle qui était retenue — exactement l'inverse de la règle
        # voulue. Ici, 0 avant 1 : la ligne de la société l'emporte.
        retenues = {}
        for ligne in lignes.sorted(lambda l: (l.type_id.sequence,
                                              l.type_id.id,
                                              0 if l.company_id else 1)):
            retenues.setdefault(ligne.type_id.id, ligne)
        return self.browse([l.id for l in retenues.values()]).sorted(
            lambda l: (l.type_id.sequence, l.type_id.id))
