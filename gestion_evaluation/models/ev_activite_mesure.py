# -*- coding: utf-8 -*-
"""La mesure d'une activité, au titre d'UNE évaluation.

L'objectif et ses activités sont la commande passée en janvier : ils
appartiennent à la période, et ne bougent plus. Ce qui a été réellement
atteint, lui, appartient à l'ÉVALUATION de décembre.

Les confondre — stocker le taux sur l'activité elle-même — avait une
conséquence qu'on ne voit qu'à l'usage : relancer une campagne sur le
même exercice retrouvait les activités **avec les mesures de la
précédente**, et deux campagnes du même exercice se seraient partagé la
saisie. C'est la même règle que partout ailleurs dans le module : une
campagne photographie ce qu'elle note.
"""
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class EvActiviteMesure(models.Model):
    _name = "ev.activite.mesure"
    _description = "Mesure d'une activité"
    _order = "goal_id, activite_sequence, id"

    appraisal_id = fields.Many2one(
        "hr.appraisal", string="Évaluation", required=True,
        ondelete="cascade", index=True)
    activite_id = fields.Many2one(
        "ev.objectif.activite", string="Activité", required=True,
        ondelete="cascade", index=True)
    goal_id = fields.Many2one(
        related="activite_id.goal_id", string="Objectif", store=True,
        index=True, readonly=True)
    activite_sequence = fields.Integer(
        related="activite_id.sequence", store=True, readonly=True)
    name = fields.Char(
        related="activite_id.name", string="Activité", readonly=True)
    resultat_attendu = fields.Text(
        related="activite_id.resultat_attendu", readonly=True)

    resultat_atteint = fields.Text(
        string="Résultat atteint",
        help="Ce qui a réellement été fait, constaté par le responsable en "
             "fin d'exercice, en regard du résultat attendu.")
    taux_realisation = fields.Float(
        string="Taux de réalisation (%)", digits=(5, 2),
        help="Part du résultat attendu qui a été atteinte. C'est la SEULE "
             "chose que le responsable pose : la note en découle.")
    note = fields.Float(
        string="Note", digits=(5, 2), compute="_compute_note",
        store=True, readonly=True,
        help="Note issue de la grille de concordance. Elle ne dépend QUE "
             "du taux : revoir la grille plus tard ne réécrit pas les "
             "notes déjà attribuées.")
    note_max = fields.Float(
        string="Note maximale", digits=(5, 2), compute="_compute_note_max")
    mesuree = fields.Boolean(
        string="Mesurée", compute="_compute_mesuree", store=True)

    _sql_constraints = [
        ("mesure_unique", "unique(appraisal_id, activite_id)",
         "Cette activité est déjà mesurée sur cette évaluation."),
    ]

    def _societe(self):
        self.ensure_one()
        return (self.appraisal_id.company_id
                or self.activite_id.employee_id.company_id
                or self.env.company)

    # `taux_realisation` SEUL en dépendance, volontairement : la note est
    # figée au moment où le taux est posé. Si la grille de concordance
    # entrait dans la dépendance, la revoir en cours de campagne
    # réécrirait des notes déjà données.
    @api.depends("taux_realisation")
    def _compute_note(self):
        Table = self.env["ev.taux.note"].sudo()
        for mesure in self:
            if not mesure.taux_realisation:
                mesure.note = 0.0
                continue
            mesure.note = Table.note_pour_taux(
                mesure.taux_realisation, mesure._societe()) or 0.0

    @api.depends("taux_realisation")
    def _compute_mesuree(self):
        for mesure in self:
            mesure.mesuree = bool(mesure.taux_realisation)

    def _compute_note_max(self):
        Table = self.env["ev.taux.note"].sudo()
        for mesure in self:
            mesure.note_max = Table.note_maximale(mesure._societe())

    @api.constrains("taux_realisation")
    def _check_taux(self):
        for mesure in self:
            if mesure.taux_realisation < 0 or mesure.taux_realisation > 100:
                raise ValidationError(_(
                    "Le taux de réalisation se situe entre 0 et 100 %."))
            if not mesure.taux_realisation:
                continue
            if self.env["ev.taux.note"].sudo().note_pour_taux(
                    mesure.taux_realisation, mesure._societe()) is None:
                raise ValidationError(_(
                    "Aucune tranche de la grille de concordance ne couvre "
                    "un taux de %(taux)s %%. Demandez au service RH de "
                    "compléter la grille (Évaluations > Configuration > "
                    "Grille de concordance).",
                    taux=("%g" % mesure.taux_realisation)))
