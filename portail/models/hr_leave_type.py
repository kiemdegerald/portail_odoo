# -*- coding: utf-8 -*-
from odoo import fields, models


class HrLeaveType(models.Model):
    _inherit = "hr.leave.type"

    portail_published = fields.Boolean(
        string="Proposé sur le portail",
        help="Si coché, ce type de congé est proposé aux employés dans le "
             "formulaire de demande du site web et dans la page de "
             "modification du portail. La liste du formulaire se met à jour "
             "automatiquement (rien à redéployer).",
    )
    portail_label = fields.Char(
        string="Libellé sur le portail",
        help="Nom affiché aux employés sur le site à la place du nom du type "
             "(facultatif). Exemple : « Congé absence » pour le type "
             "« Absence déductible ».",
    )
    portail_allow_past_dates = fields.Boolean(
        string="Dates passées autorisées sur le portail",
        help="Si coché, les employés peuvent soumettre une demande de ce type "
             "sur des dates déjà écoulées (régularisation après coup — cas "
             "typique : l'arrêt maladie déclaré au retour). Sinon, toute "
             "demande commençant avant aujourd'hui est refusée.",
    )
