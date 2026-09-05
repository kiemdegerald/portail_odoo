# -*- coding: utf-8 -*-
from odoo import fields, models, _
from odoo.exceptions import UserError


class GmDecisionWizard(models.TransientModel):
    """Fenêtre de décision du valideur : refus et renvoi exigent un
    commentaire (il sera visible du demandeur et tracé dans le dossier)."""
    _name = "gm.decision.wizard"
    _description = "Décision sur une demande de mission"

    mission_id = fields.Many2one(
        "gm.mission", required=True, readonly=True)
    membre_id = fields.Many2one(
        "gm.mission.membre", string="Missionnaire", readonly=True,
        help="Renseigné quand la décision porte sur la déclaration de "
             "retour d'UN missionnaire, et non sur la demande entière.")
    action = fields.Selection([
        ("refuse", "Refuser la demande"),
        ("send_back", "Renvoyer pour correction"),
        ("cancel", "Annuler la mission"),
        ("renvoi_declaration", "Renvoyer la déclaration de retour"),
    ], string="Décision", required=True, readonly=True)
    comment = fields.Text(
        string="Commentaire", required=True,
        help="Obligatoire — il sera visible par le demandeur.")

    def action_confirm(self):
        self.ensure_one()
        if not (self.comment and self.comment.strip()):
            raise UserError(_("Le commentaire est obligatoire."))
        if self.action == "renvoi_declaration":
            self.membre_id.action_declaration_renvoyee(motif=self.comment)
        elif self.action == "refuse":
            self.mission_id.action_refuse_step(comment=self.comment)
        elif self.action == "cancel":
            self.mission_id.action_cancel(reason=self.comment)
        else:
            self.mission_id.action_send_back(comment=self.comment)
        return {"type": "ir.actions.act_window_close"}
