# -*- coding: utf-8 -*-
"""Les trames de commentaire d'Odoo n'ont pas cours ici.

Le standard pré-remplit les zones de commentaire de chaque évaluation
avec un questionnaire générique, recopié depuis la société. La banque
note sur SA grille d'appréciation : ces questions n'ont rien à y faire,
et un texte que personne n'a écrit dans la zone de saisie d'un agent est
au mieux déroutant, au pire recopié tel quel dans son dossier.
"""
from odoo import api, models


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        societes = super().create(vals_list)
        # Le standard réinstalle ses trames APRÈS la création (voir
        # ``hr_appraisal/models/res_company.py``). Les vider ici est donc
        # le seul endroit qui tienne : sans cela, chaque nouvelle société
        # ramènerait le questionnaire générique, et toutes ses évaluations
        # naîtraient avec un commentaire déjà rempli.
        societes.sudo().write({
            "appraisal_employee_feedback_template": False,
            "appraisal_manager_feedback_template": False,
        })
        return societes
