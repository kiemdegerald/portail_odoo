# -*- coding: utf-8 -*-
"""Extension de res.company : auto-rattachement de l'utilisateur API.

Toute nouvelle societe cree doit inclure l'utilisateur technique de l'API dans
ses membres, faute de quoi les offres de cette societe seraient invisibles pour
l'API (regle multi-societe d'Odoo) et n'apparaitraient pas sur le site web.
"""
import logging

from odoo import api, models

from ..const import API_USER_XMLID

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        api_user = self.env.ref(API_USER_XMLID, raise_if_not_found=False)
        if api_user:
            # Rattacher l'utilisateur technique aux nouvelles societes pour que
            # leurs offres publiees restent diffusees par l'API.
            api_user.sudo().write(
                {"company_ids": [(4, c.id) for c in companies]})
            _logger.info(
                "GR: utilisateur technique rattache aux nouvelles societes %s.",
                companies.ids)
        return companies
