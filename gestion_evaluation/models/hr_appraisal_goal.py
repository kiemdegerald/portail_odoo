# -*- coding: utf-8 -*-
"""Rattachement d'un objectif à sa campagne — donc à son exercice.

Le standard Odoo empile les objectifs d'un agent dans une liste plate, sans
notion d'année : au moment d'évaluer l'exercice 2027, on voit encore ceux de
2026. Ce rattachement permet de ne jamais les mélanger.
"""
from odoo import api, fields, models


class HrAppraisalGoal(models.Model):
    _inherit = "hr.appraisal.goal"

    ev_campagne_id = fields.Many2one(
        "ev.campagne", string="Campagne", index=True, copy=False,
        # La campagne peut disparaître, l'objectif reste : il documente ce qui
        # avait été demandé à l'agent.
        ondelete="set null",
        help="Campagne d'évaluation au titre de laquelle cet objectif a été "
             "fixé. Vide pour un objectif hors campagne.")
    # L'objectif se fixe en DÉBUT d'exercice, au titre d'une PÉRIODE —
    # des mois avant qu'une campagne d'évaluation n'existe. Le lien à la
    # campagne reste, pour les objectifs saisis depuis une évaluation.
    ev_periode_id = fields.Many2one(
        "ev.periode.objectifs", string="Période d'objectifs", index=True,
        copy=False, ondelete="set null",
        help="Période au titre de laquelle cet objectif a été fixé.")
    ev_exercice = fields.Char(
        string="Exercice", compute="_compute_ev_exercice",
        store=True, index=True, readonly=False,
        help="Année au titre de laquelle l'objectif est fixé : reprise de "
             "la période, ou à défaut de la campagne. C'est par elle que "
             "la campagne d'évaluation retrouve les objectifs.")

    @api.depends("ev_periode_id.exercice", "ev_campagne_id.exercice")
    def _compute_ev_exercice(self):
        for objectif in self:
            objectif.ev_exercice = (objectif.ev_periode_id.exercice
                                    or objectif.ev_campagne_id.exercice
                                    or objectif.ev_exercice)

    @api.onchange("employee_id")
    def _onchange_employee_ev_campagne(self):
        """Rattache l'objectif à la campagne de l'agent, quand il n'y a pas
        d'ambiguïté.

        Sans cela, un objectif créé depuis le menu « Objectifs » naît sans
        campagne : il échappe au cloisonnement par exercice et n'apparaît
        dans aucun filtre. On ne devine rien pour autant — si l'agent est
        engagé dans plusieurs campagnes ouvertes, on laisse le choix.
        """
        if self.ev_campagne_id or not self.employee_id:
            return
        campagnes = self.env["ev.campagne"].search([
            ("state", "in", ("objectifs", "running")),
            ("appraisal_ids.employee_id", "=", self.employee_id._origin.id),
        ])
        if len(campagnes) == 1:
            self.ev_campagne_id = campagnes
        elif len(campagnes) > 1:
            return {"warning": {
                "title": "Plusieurs campagnes en cours",
                "message": "%s participe à %d campagnes ouvertes (%s). "
                           "Choisissez celle au titre de laquelle cet "
                           "objectif est fixé." % (
                               self.employee_id.name, len(campagnes),
                               ", ".join(campagnes.mapped("name"))),
            }}
