# -*- coding: utf-8 -*-
"""Grille d'évaluation : la fiche d'appréciation de la banque, à l'écran.

Trois niveaux, ni plus ni moins, calqués sur le document réel :

    BLOC        Savoir-faire
      THÈME       Performance dans son poste
        CRITÈRE     Qualité du travail fourni      <- on note ici
        CRITÈRE     Respect des délais

La note remonte par MOYENNES SIMPLES, exactement comme les formules du
fichier Excel de la BADF :
    note d'un thème  = moyenne de ses critères notés
    note d'un bloc   = moyenne de ses thèmes notés
    note globale     = moyenne des blocs notés
Aucune pondération : la banque n'en utilise pas.
"""
from markupsafe import Markup, escape

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


def _moyenne(valeurs):
    """Moyenne des valeurs renseignées, None s'il n'y en a aucune."""
    valeurs = [v for v in valeurs if v is not None]
    return (sum(valeurs) / len(valeurs)) if valeurs else None


class EvEchelleNiveau(models.Model):
    """Échelle de notation : les niveaux proposés à l'évaluateur.

    Cinq niveaux à la BADF (« Point d'amélioration prioritaire » = 1 à
    « Excellence » = 5), mais le nombre et les libellés sont libres. La
    VALEUR du niveau est recopiée sur la note au moment de la saisie :
    modifier l'échelle ensuite ne réécrit jamais une notation déjà faite.
    """
    _name = "ev.echelle.niveau"
    _description = "Niveau de l'échelle de notation"
    _order = "sequence, valeur, id"

    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(string="Niveau", required=True)
    valeur = fields.Float(string="Note correspondante", required=True)
    active = fields.Boolean(default=True)

    @api.constrains("valeur")
    def _check_valeur(self):
        for niveau in self:
            if niveau.valeur < 0:
                raise ValidationError(_(
                    "La note d'un niveau ne peut pas être négative."))

    def name_get(self):
        return [(n.id, "%s (%g)" % (n.name, n.valeur)) for n in self]


class EvGrille(models.Model):
    _name = "ev.grille"
    _description = "Grille d'évaluation"
    _order = "name"

    name = fields.Char(string="Intitulé", required=True)
    description = fields.Text(string="Note d'usage")
    company_id = fields.Many2one(
        "res.company", string="Société",
        help="Vide = grille commune à toutes les sociétés.")
    active = fields.Boolean(default=True)

    bloc_ids = fields.One2many(
        "ev.grille.bloc", "grille_id", string="Blocs")
    theme_ids = fields.One2many(
        "ev.grille.theme", "grille_id", string="Thèmes")
    critere_ids = fields.One2many(
        "ev.grille.critere", "grille_id", string="Critères",
        help="Tous les critères de la grille, à plat : la façon la plus "
             "rapide d'en ajouter ou d'en retirer.")
    apercu = fields.Html(
        string="Aperçu", compute="_compute_apercu", sanitize=False)
    nb_criteres = fields.Integer(
        string="Nombre de critères", compute="_compute_nb_criteres")
    campagne_ids = fields.One2many(
        "ev.campagne", "grille_id", string="Campagnes")

    @api.depends("critere_ids")
    def _compute_nb_criteres(self):
        for grille in self:
            grille.nb_criteres = len(grille.critere_ids)

    @api.depends("bloc_ids.name", "bloc_ids.sequence",
                 "bloc_ids.theme_ids.name", "bloc_ids.theme_ids.sequence",
                 "bloc_ids.theme_ids.critere_ids.name",
                 "bloc_ids.theme_ids.critere_ids.sequence")
    def _compute_apercu(self):
        for grille in self:
            grille.apercu = grille._rendu_apercu()

    def _rendu_apercu(self):
        """La grille entière, lisible d'un coup d'œil — sans pourcentage :
        tous les critères d'un thème comptent pareil, tous les thèmes d'un
        bloc aussi, et les deux blocs pèsent autant l'un que l'autre."""
        self.ensure_one()
        if not self.bloc_ids:
            return Markup(
                '<p class="text-muted mb-0">Grille vide. Ajoutez vos blocs, '
                'leurs thèmes et leurs critères dans l\'onglet '
                '<b>Structure</b>.</p>')
        lignes = []
        for bloc in self.bloc_ids:
            lignes.append('<tr><td><b>%s</b></td></tr>' % escape(bloc.name or ""))
            for theme in bloc.theme_ids:
                lignes.append(
                    '<tr><td style="padding-left:2em"><i>%s</i></td></tr>'
                    % escape(theme.name or ""))
                for critere in theme.critere_ids:
                    lignes.append(
                        '<tr><td style="padding-left:4em">%s</td></tr>'
                        % escape(critere.name or ""))
        return Markup(
            '<table class="table table-sm" style="width:100%%">'
            '<tbody>%s</tbody>'
            '<tfoot><tr><td class="text-muted small">'
            'Note d\'un thème = moyenne de ses critères &nbsp;•&nbsp; '
            'note d\'un bloc = moyenne de ses thèmes &nbsp;•&nbsp; '
            'note globale = moyenne des blocs.</td></tr></tfoot>'
            '</table>' % "".join(lignes))

    def action_dupliquer(self):
        """Crée une copie modifiable, structure comprise."""
        self.ensure_one()
        copie = self.copy({"name": _("%s (copie)", self.name)})
        for bloc in self.bloc_ids:
            nouveau_bloc = bloc.copy({"grille_id": copie.id})
            nouveau_bloc.theme_ids.unlink()
            for theme in bloc.theme_ids:
                nouveau_theme = theme.copy({"bloc_id": nouveau_bloc.id})
                nouveau_theme.critere_ids.unlink()
                for critere in theme.critere_ids:
                    critere.copy({"theme_id": nouveau_theme.id})
        return {
            "type": "ir.actions.act_window",
            "res_model": "ev.grille",
            "res_id": copie.id,
            "view_mode": "form",
        }

    def _score(self, notes):
        """Note globale : moyenne des blocs notés.

        ``notes`` : {id de critère: valeur}. Les critères non notés sont
        simplement ignorés — ils ne tirent pas la note vers le bas.
        """
        self.ensure_one()
        return _moyenne([bloc._score(notes) for bloc in self.bloc_ids])


class EvGrilleBloc(models.Model):
    """Grande partie de la fiche : « Savoir-faire », « Savoir-être »...
    Les blocs s'ajoutent et se retirent librement."""
    _name = "ev.grille.bloc"
    _description = "Bloc d'une grille d'évaluation"
    _order = "sequence, id"

    grille_id = fields.Many2one(
        "ev.grille", string="Grille", required=True, ondelete="cascade",
        index=True)
    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(string="Bloc", required=True)
    theme_ids = fields.One2many(
        "ev.grille.theme", "bloc_id", string="Thèmes")
    nb_criteres = fields.Integer(
        string="Critères", compute="_compute_nb_criteres")

    @api.depends("theme_ids.critere_ids")
    def _compute_nb_criteres(self):
        for bloc in self:
            bloc.nb_criteres = len(bloc.theme_ids.critere_ids)

    def _score(self, notes):
        self.ensure_one()
        return _moyenne([theme._score(notes) for theme in self.theme_ids])


class EvGrilleTheme(models.Model):
    """Regroupement de critères à l'intérieur d'un bloc : « Qualités
    relationnelles », « Autonomie »... Un bloc peut n'en avoir qu'un."""
    _name = "ev.grille.theme"
    _description = "Thème d'une grille d'évaluation"
    _order = "bloc_sequence, sequence, id"

    bloc_id = fields.Many2one(
        "ev.grille.bloc", string="Bloc", required=True, ondelete="cascade",
        index=True)
    grille_id = fields.Many2one(
        related="bloc_id.grille_id", store=True, index=True)
    bloc_sequence = fields.Integer(
        related="bloc_id.sequence", store=True, index=True)
    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(string="Thème", required=True)
    critere_ids = fields.One2many(
        "ev.grille.critere", "theme_id", string="Critères")
    nb_criteres = fields.Integer(
        string="Critères", compute="_compute_nb_criteres")

    @api.depends("critere_ids")
    def _compute_nb_criteres(self):
        for theme in self:
            theme.nb_criteres = len(theme.critere_ids)

    def name_get(self):
        return [(t.id, "%s / %s" % (t.bloc_id.name or "", t.name or ""))
                for t in self]

    def _score(self, notes):
        self.ensure_one()
        return _moyenne([notes.get(c.id) for c in self.critere_ids])


class EvGrilleCritere(models.Model):
    """Ligne notée par l'évaluateur."""
    _name = "ev.grille.critere"
    _description = "Critère d'une grille d'évaluation"
    _order = "bloc_sequence, theme_sequence, sequence, id"

    theme_id = fields.Many2one(
        "ev.grille.theme", string="Thème", required=True,
        ondelete="cascade", index=True)
    bloc_id = fields.Many2one(
        related="theme_id.bloc_id", store=True, index=True)
    grille_id = fields.Many2one(
        related="theme_id.grille_id", store=True, index=True)
    bloc_sequence = fields.Integer(
        related="theme_id.bloc_sequence", store=True, index=True)
    theme_sequence = fields.Integer(
        related="theme_id.sequence", store=True, index=True)
    sequence = fields.Integer(string="Ordre", default=10)
    name = fields.Char(string="Critère", required=True)
    description = fields.Char(
        string="Précision",
        help="Aide affichée à l'évaluateur pour cadrer son appréciation.")

    def name_get(self):
        return [(c.id, c.name or "") for c in self]
