# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class EvDecisionWizard(models.TransientModel):
    """Fenêtre de décision sur une phase du circuit.

    Le renvoi exige un commentaire : il indique au précédent intervenant ce
    qu'il doit corriger, et il est tracé au dossier.
    """
    _name = "ev.decision.wizard"
    _description = "Décision sur une phase d'évaluation"

    appraisal_id = fields.Many2one(
        "hr.appraisal", string="Évaluation", required=True, readonly=True)
    action = fields.Selection([
        ("valider", "Valider la phase"),
        ("renvoyer", "Renvoyer pour correction"),
    ], string="Décision", required=True, readonly=True)
    phase_nom = fields.Char(
        string="Phase en cours", related="appraisal_id.ev_phase_courante_id.name",
        readonly=True)
    comment = fields.Text(
        string="Commentaire",
        help="Obligatoire pour un renvoi. Facultatif pour une validation.")

    def action_confirm(self):
        self.ensure_one()
        if self.action == "renvoyer":
            if not (self.comment and self.comment.strip()):
                raise UserError(_(
                    "Le commentaire est obligatoire pour un renvoi."))
            self.appraisal_id.action_ev_renvoyer(comment=self.comment)
        else:
            self.appraisal_id.action_ev_valider_etape(comment=self.comment)
        return {"type": "ir.actions.act_window_close"}
