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
    ev_exercice = fields.Char(
        string="Exercice", related="ev_campagne_id.exercice",
        store=True, index=True,
        help="Reprise de l'exercice de la campagne : permet de retrouver et "
             "de regrouper les objectifs année par année.")

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
            ("state", "=", "running"),
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
