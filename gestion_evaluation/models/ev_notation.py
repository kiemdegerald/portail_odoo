# -*- coding: utf-8 -*-
"""La notation d'une évaluation : une ligne par critère de la grille.

La VALEUR du niveau est recopiée sur la ligne au moment de la saisie. Une
échelle modifiée plus tard ne réécrit donc jamais une notation déjà faite.
"""
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class EvNotationLigne(models.Model):
    _name = "ev.notation.ligne"
    _description = "Note d'un critère sur une évaluation"
    _order = "sequence, id"

    appraisal_id = fields.Many2one(
        "hr.appraisal", string="Évaluation", required=True,
        ondelete="cascade", index=True)
    critere_id = fields.Many2one(
        "ev.grille.critere", string="Critère", required=True,
        ondelete="restrict")
    theme_id = fields.Many2one(
        "ev.grille.theme", string="Thème",
        related="critere_id.theme_id", store=True)
    bloc_id = fields.Many2one(
        "ev.grille.bloc", string="Bloc",
        related="critere_id.bloc_id", store=True)
    sequence = fields.Integer(string="Ordre")

    niveau_id = fields.Many2one(
        "ev.echelle.niveau", string="Appréciation",
        help="Niveau retenu par l'évaluateur.")
    valeur = fields.Float(
        string="Note", compute="_compute_valeur", store=True, readonly=True,
        help="Note du niveau retenu, figée au moment de la saisie.")
    commentaire = fields.Char(string="Observation")

    @api.depends("niveau_id")
    def _compute_valeur(self):
        for ligne in self:
            ligne.valeur = ligne.niveau_id.valeur if ligne.niveau_id else 0.0

    _sql_constraints = [
        ("critere_unique", "unique(appraisal_id, critere_id)",
         "Ce critère est déjà présent sur cette évaluation."),
    ]

    def name_get(self):
        return [(l.id, l.critere_id.name or "") for l in self]

    # ------------------------------------------------------------------
    # Verrou de saisie
    # ------------------------------------------------------------------
    # Une note est une pièce du dossier d'un agent : elle ne se saisit que
    # pendant la phase qui y donne droit, et plus du tout une fois
    # l'évaluation close. Le contrôle est ICI, au niveau du modèle : masquer
    # le champ dans la vue n'empêcherait ni l'import, ni l'appel RPC direct.
    @api.model
    def _ev_check_saisie(self, appraisals, operation):
        if self.env.su or self.env.context.get("ev_notation_systeme"):
            return
        for appraisal in appraisals:
            motif = appraisal._ev_motif_notation_fermee()
            if motif:
                raise UserError(_(
                    "Notation impossible (%(op)s).\n\n%(motif)s",
                    op=operation, motif=motif))

    @api.model_create_multi
    def create(self, vals_list):
        self._ev_check_saisie(
            self.env["hr.appraisal"].browse([
                v["appraisal_id"] for v in vals_list if v.get("appraisal_id")]),
            _("création"))
        return super().create(vals_list)

    def write(self, vals):
        self._ev_check_saisie(self.mapped("appraisal_id"), _("modification"))
        return super().write(vals)

    def unlink(self):
        self._ev_check_saisie(self.mapped("appraisal_id"), _("suppression"))
        return super().unlink()
