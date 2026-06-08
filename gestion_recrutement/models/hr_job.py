# -*- coding: utf-8 -*-
"""Extension du modele hr.job (offre d'emploi).

Ajoute les champs metier diffuses vers le site, les questions de filtre
parametrables, la serialisation vers le format d'echange, l'evaluation des
regles de filtre et la synchronisation push vers le site (bouton manuel ou
automatique a l'enregistrement).
"""
import json
import logging

import requests

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.gestion_recrutement.const import (
    CONTRACT_TYPES,
    PARAM_AUTO_SYNC,
    PARAM_SITE_WEBHOOK_KEY,
    PARAM_SITE_WEBHOOK_URL,
    RULE_ACTION_NONE,
    RULE_ACTION_PRIORITY,
)

_logger = logging.getLogger(__name__)


class HrJob(models.Model):
    _inherit = "hr.job"

    gr_location = fields.Char(string="Localisation")
    gr_contract_type = fields.Selection(
        selection=CONTRACT_TYPES, string="Type de contrat",
    )
    gr_experience_required = fields.Char(
        string="Experience requise", help="Ex. 2 a 4 ans. Texte libre.",
    )
    gr_short_summary = fields.Text(
        string="Resume court",
        help="Accroche affichee dans les listes d'offres du site.",
    )
    gr_missions = fields.Html(string="Missions / Responsabilites", sanitize=True)
    gr_candidate_profile = fields.Html(
        string="Profil recherche / Competences", sanitize=True)
    gr_benefits = fields.Html(string="Avantages", sanitize=True)

    gr_is_published = fields.Boolean(
        string="Publie sur le site web", default=False, copy=False,
        help="Si coche, l'offre est renvoyee par la passerelle de lecture.",
    )
    gr_document_count = fields.Integer(
        string="Documents joints", compute="_compute_gr_document_count",
    )
    filter_question_ids = fields.One2many(
        "gr.filter.question", "job_id", string="Questions de filtre",
        copy=True,
    )

    def _compute_gr_document_count(self):
        Attachment = self.env["ir.attachment"]
        for job in self:
            job.gr_document_count = Attachment.search_count([
                ("res_model", "=", "hr.job"),
                ("res_id", "=", job.id),
            ])

    @api.model
    def _gr_published_domain(self):
        return [("gr_is_published", "=", True)]

    def get_gr_published_jobs(self):
        return self.search(self._gr_published_domain())

    def _gr_get_documents(self):
        self.ensure_one()
        return self.env["ir.attachment"].search([
            ("res_model", "=", "hr.job"),
            ("res_id", "=", self.id),
        ])

    def _gr_active_questions(self):
        self.ensure_one()
        return self.filter_question_ids.filtered(lambda q: q.active)

    def gr_serialize(self):
        self.ensure_one()
        documents = [
            {
                "id": att.id,
                "name": att.name,
                "mimetype": att.mimetype or "",
                "url": "/api/recruitment/jobs/%d/documents/%d" % (self.id, att.id),
            }
            for att in self._gr_get_documents()
        ]
        return {
            "id": self.id,
            "title": self.name or "",
            "location": self.gr_location or "",
            "contract_type": self.gr_contract_type or "",
            "experience_required": self.gr_experience_required or "",
            "department": self.department_id.name or "",
            "short_summary": self.gr_short_summary or "",
            "missions": self.gr_missions or "",
            "profile": self.gr_candidate_profile or "",
            "benefits": self.gr_benefits or "",
            "positions_available": self.no_of_recruitment,
            "documents": documents,
            "filter_questions": [
                q.gr_serialize() for q in self._gr_active_questions()
            ],
        }

    def gr_missing_required(self, answers):
        self.ensure_one()
        missing = []
        for question in self._gr_active_questions():
            if not question.is_required:
                continue
            value = answers.get(question.id)
            if value is None or str(value).strip() == "":
                missing.append(question.name)
        return missing

    def gr_evaluate_answers(self, answers):
        self.ensure_one()
        plan = {"action": RULE_ACTION_NONE, "stage_id": None, "reason": None}
        best_priority = 0
        for question in self._gr_active_questions():
            value = answers.get(question.id)
            if value is None:
                continue
            # Une question peut porter plusieurs règles : on retient l'action
            # de plus haute priorité parmi celles qui se déclenchent.
            for rule in question.rule_ids:
                if rule.rule_action == RULE_ACTION_NONE:
                    continue
                if not rule.matches(value):
                    continue
                priority = RULE_ACTION_PRIORITY.get(rule.rule_action, 0)
                if priority > best_priority:
                    best_priority = priority
                    plan = {
                        "action": rule.rule_action,
                        "stage_id": rule.rule_stage_id.id or None,
                        "reason": question.name,
                    }
        return plan

    def _gr_param(self, key, default=""):
        return self.env["ir.config_parameter"].sudo().get_param(key, default)

    def _gr_push_to_site(self):
        url = self._gr_param(PARAM_SITE_WEBHOOK_URL)
        if not url:
            return False
        key = self._gr_param(PARAM_SITE_WEBHOOK_KEY)
        payload = {"jobs": [job.gr_serialize() for job in self]}
        headers = {"Content-Type": "application/json"}
        if key:
            headers["X-Site-Key"] = key
        try:
            resp = requests.post(
                url, data=json.dumps(payload), headers=headers, timeout=10,
            )
            resp.raise_for_status()
            _logger.info("GR: %s offre(s) synchronisee(s) vers le site.", len(self))
            return True
        except Exception as exc:  # noqa: BLE001
            _logger.warning("GR: echec de la synchronisation vers le site : %s", exc)
            return False

    def action_gr_sync_to_site(self):
        url = self._gr_param(PARAM_SITE_WEBHOOK_URL)
        if not url:
            raise UserError(
                "Aucune URL de webhook du site n'est configuree "
                "(parametre gestion_recrutement.site_webhook_url)."
            )
        if not self._gr_push_to_site():
            raise UserError(
                "La synchronisation a echoue. Consultez les journaux du "
                "serveur pour le detail (URL joignable ? cle correcte ?)."
            )
        return True

    def _gr_auto_sync_enabled(self):
        return self._gr_param(PARAM_AUTO_SYNC, "0") in ("1", "True", "true")

    @api.model_create_multi
    def create(self, vals_list):
        jobs = super().create(vals_list)
        if self._gr_auto_sync_enabled():
            jobs.filtered("gr_is_published")._gr_push_to_site()
        return jobs

    def write(self, vals):
        res = super().write(vals)
        if self._gr_auto_sync_enabled():
            self.filtered("gr_is_published")._gr_push_to_site()
        return res
