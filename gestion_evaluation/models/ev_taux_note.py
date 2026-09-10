# -*- coding: utf-8 -*-
"""La grille de concordance : du taux de réalisation à la note.

Le responsable ne donne jamais une note. Il constate ce qui a été fait et
pose un taux ; la note en découle par cette table. C'est ce qui fait que
deux responsables différents notent la même performance de la même façon.

La table est configurable par le service RH : chaque banque a la sienne,
et elle peut la revoir d'un exercice à l'autre.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EvTauxNote(models.Model):
    _name = "ev.taux.note"
    _description = "Tranche de concordance taux / note"
    _order = "taux_min, id"
    _rec_name = "display_name"

    taux_min = fields.Float(
        string="Taux minimum (%)", required=True, digits=(5, 2),
        help="Borne basse de la tranche, incluse.")
    taux_max = fields.Float(
        string="Taux maximum (%)", required=True, digits=(5, 2), default=100.0,
        help="Borne haute de la tranche, incluse.")
    note = fields.Float(
        string="Note", required=True, digits=(5, 2),
        help="Note attribuée à toute activité dont le taux tombe dans "
             "cette tranche.")
    company_id = fields.Many2one(
        "res.company", string="Société",
        help="Vide = table commune à toutes les sociétés.")
    active = fields.Boolean(default=True)

    @api.depends("taux_min", "taux_max", "note")
    def _compute_display_name(self):
        for tranche in self:
            tranche.display_name = _(
                "%(min)s à %(max)s %% → %(note)s",
                min=("%g" % tranche.taux_min), max=("%g" % tranche.taux_max),
                note=("%g" % tranche.note))

    @api.constrains("taux_min", "taux_max", "note")
    def _check_bornes(self):
        for tranche in self:
            if tranche.taux_min > tranche.taux_max:
                raise ValidationError(_(
                    "La borne basse (%(min)s %%) dépasse la borne haute "
                    "(%(max)s %%).",
                    min=("%g" % tranche.taux_min),
                    max=("%g" % tranche.taux_max)))
            if tranche.taux_min < 0 or tranche.taux_max > 100:
                raise ValidationError(_(
                    "Un taux de réalisation se situe entre 0 et 100 %."))
            if tranche.note < 0:
                raise ValidationError(_("Une note ne peut pas être négative."))

    @api.constrains("taux_min", "taux_max", "company_id")
    def _check_chevauchement(self):
        """Deux tranches qui se recouvrent rendraient la note indécise :
        le même taux donnerait deux notes différentes selon l'ordre de
        lecture."""
        for tranche in self:
            autres = self.search([
                ("id", "!=", tranche.id),
                ("company_id", "=", tranche.company_id.id),
                ("taux_min", "<=", tranche.taux_max),
                ("taux_max", ">=", tranche.taux_min),
            ], limit=1)
            if autres:
                raise ValidationError(_(
                    "Cette tranche (%(a)s) recouvre « %(b)s ». Deux "
                    "tranches qui se chevauchent rendent la note indécise : "
                    "corrigez les bornes.",
                    a=tranche.display_name, b=autres.display_name))

    # ------------------------------------------------------------------
    # Lecture
    # ------------------------------------------------------------------
    @api.model
    def _table_applicable(self, company):
        """La table applicable : celle de la société, sinon la commune.

        On ne mélange pas les deux — une société qui définit sa propre
        table la définit en entier.
        """
        propre = self.search([("company_id", "=", company.id)])
        return propre or self.search([("company_id", "=", False)])

    @api.model
    def note_pour_taux(self, taux, company):
        """La note correspondant à un taux. Renvoie None si aucune tranche
        ne le couvre — au lieu d'inventer un zéro qui passerait
        inaperçu."""
        table = self._table_applicable(company)
        for tranche in table:
            if tranche.taux_min <= taux <= tranche.taux_max:
                return tranche.note
        return None

    @api.model
    def note_maximale(self, company):
        """La note la plus haute de la table : c'est le « sur combien »
        des objectifs sur la fiche."""
        table = self._table_applicable(company)
        return max(table.mapped("note")) if table else 0.0

    @api.model
    def trous_de_couverture(self, company):
        """Les intervalles de 0 à 100 % que la table ne couvre pas.

        Une table trouée laisse des taux sans note, et le responsable ne
        le découvre qu'au moment de noter.
        """
        table = self._table_applicable(company).sorted("taux_min")
        trous, curseur = [], 0.0
        for tranche in table:
            if tranche.taux_min > curseur + 0.01:
                trous.append((curseur, tranche.taux_min))
            curseur = max(curseur, tranche.taux_max)
        if curseur < 99.99:
            trous.append((curseur, 100.0))
        return trous
