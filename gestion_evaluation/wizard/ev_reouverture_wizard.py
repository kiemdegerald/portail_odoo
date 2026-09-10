# -*- coding: utf-8 -*-
"""Rouvrir une période de fixation des objectifs : on dit pourquoi.

Rouvrir n'est pas un geste anodin. La période a été fermée, la campagne
d'évaluation a peut-être déjà été lancée sur ces objectifs — et la
réouverture permet d'en ajouter, d'en retirer, d'en modifier. Six mois
plus tard, quand un agent conteste sa note, il faut pouvoir répondre à
deux questions : qui a rouvert, et pour quelle raison.

D'où cette fenêtre : le motif est obligatoire, l'auteur est celui qui
clique, et l'un comme l'autre restent au dossier.
"""
from odoo import fields, models, _
from odoo.exceptions import UserError


class EvReouvertureWizard(models.TransientModel):
    _name = "ev.reouverture.wizard"
    _description = "Réouverture d'une période d'objectifs"

    periode_id = fields.Many2one(
        "ev.periode.objectifs", string="Période", required=True,
        readonly=True)
    exercice = fields.Char(related="periode_id.exercice", readonly=True)
    nb_agents = fields.Integer(related="periode_id.nb_agents", readonly=True)
    nb_avec_objectif = fields.Integer(
        related="periode_id.nb_avec_objectif", readonly=True)
    campagne_lancee = fields.Boolean(
        string="Une campagne note déjà ces objectifs",
        compute="_compute_campagne_lancee")
    motif = fields.Text(
        string="Motif de la réouverture", required=True,
        help="Pourquoi cette période est rouverte : un agent oublié, un "
             "responsable absent pendant la période, une erreur à "
             "corriger. Ce motif reste au dossier.")

    def _compute_campagne_lancee(self):
        Campagne = self.env["ev.campagne"].sudo()
        for wizard in self:
            periode = wizard.periode_id
            wizard.campagne_lancee = bool(periode) and bool(Campagne.search([
                ("exercice", "=", periode.exercice),
                ("company_id", "=", periode.company_id.id),
                ("state", "in", ("running", "closed")),
            ], limit=1))

    def action_confirm(self):
        self.ensure_one()
        if not (self.motif and self.motif.strip()):
            raise UserError(_(
                "Indiquez le motif de la réouverture : c'est lui qui "
                "expliquera, plus tard, pourquoi les objectifs de cet "
                "exercice ont été modifiés après coup."))
        self.periode_id.action_rouvrir(motif=self.motif)
        return {"type": "ir.actions.act_window_close"}
