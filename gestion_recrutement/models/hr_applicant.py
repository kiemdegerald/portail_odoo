# -*- coding: utf-8 -*-
"""Extension du modele hr.applicant (candidature).

Porte la tracabilite de l'origine site web, les reponses aux questions
de filtre, et la logique de creation d'une candidature recue par la
passerelle : placement a l'etape initiale du pipeline existant, application
des regles de filtre (archivage / changement d'etape) et attachement des
documents (CV, lettre de motivation).
"""
import base64
import logging

from odoo import api, fields, models

from odoo.addons.gestion_recrutement.const import (
    PARAM_AUTO_CREATE_EMPLOYEE,
    RULE_ACTION_ARCHIVE,
    RULE_ACTION_SET_STAGE,
    SOURCE_CHANNEL_WEBSITE,
)

_logger = logging.getLogger(__name__)


class HrApplicant(models.Model):
    _inherit = "hr.applicant"

    gr_source_channel = fields.Char(
        string="Canal source", readonly=True, copy=False,
        help="Renseigne automatiquement (ex. website).",
    )
    gr_external_ref = fields.Char(
        string="Reference externe", readonly=True, copy=False, index=True,
        help="Identifiant cote site, utilise pour garantir l'idempotence.",
    )
    filter_answer_ids = fields.One2many(
        "gr.applicant.answer", "applicant_id",
        string="Reponses aux questions de filtre", readonly=True,
    )

    # ------------------------------------------------------------------
    # Creation automatique de l'employe a l'etape d'embauche
    # ------------------------------------------------------------------
    def write(self, vals):
        res = super().write(vals)
        if vals.get("stage_id"):
            self._gr_maybe_create_employee(vals["stage_id"])
        return res

    def _gr_auto_create_enabled(self):
        return self.env["ir.config_parameter"].sudo().get_param(
            PARAM_AUTO_CREATE_EMPLOYEE, "0") in ("1", "True", "true")

    def _gr_maybe_create_employee(self, stage_id):
        """Cree l'employe si la nouvelle etape est marquee « embauche ».

        Declenche par le passage a une etape dont ``hired_stage`` est vrai
        (ex. « Signature du contrat »). Anti-doublon via ``emp_id``. Une erreur
        de creation n'empeche jamais le changement d'etape (log seulement).
        """
        if not self._gr_auto_create_enabled():
            return
        stage = self.env["hr.recruitment.stage"].browse(stage_id)
        if not stage.exists() or not stage.hired_stage:
            return
        for applicant in self:
            if applicant.emp_id:
                continue
            try:
                action = applicant.create_employee_from_applicant()
                if not applicant.emp_id and isinstance(action, dict) and action.get("res_id"):
                    applicant.emp_id = action["res_id"]
                _logger.info(
                    "GR: employe cree automatiquement depuis la candidature %s "
                    "(etape d'embauche « %s »)", applicant.id, stage.name)
            except Exception as exc:  # noqa: BLE001
                _logger.warning(
                    "GR: creation auto de l'employe echouee (candidature %s) : %s",
                    applicant.id, exc)

    @api.model
    def _gr_initial_stage(self, job):
        return self.env["hr.recruitment.stage"].search(
            ["|", ("job_ids", "=", False), ("job_ids", "in", job.id)],
            order="sequence asc, id asc", limit=1,
        )

    @api.model
    def _gr_find_by_external_ref(self, external_ref):
        if not external_ref:
            return self.browse()
        return self.search([("gr_external_ref", "=", external_ref)], limit=1)

    @api.model
    def create_from_website(
        self, job, payload, answers=None, plan=None,
        cv=None, cover_letter=None,
    ):
        answers = answers or {}
        plan = plan or {}

        if plan.get("action") == RULE_ACTION_SET_STAGE and plan.get("stage_id"):
            stage_id = plan["stage_id"]
        else:
            stage = self._gr_initial_stage(job)
            stage_id = stage.id if stage else False

        # Intake par API : la creation ne doit jamais dependre de l'envoi d'un
        # e-mail (l'etape initiale peut porter un modele d'accuse de reception).
        # On desactive le tracking/notification automatique pour garantir que la
        # candidature est toujours enregistree, meme sans serveur mail configure.
        applicant = self.with_context(
            tracking_disable=True,
            mail_create_nolog=True,
            mail_create_nosubscribe=True,
        ).create({
            "name": payload.get("name") or job.name or "Candidature",
            "partner_name": payload.get("name"),
            "email_from": payload.get("email"),
            "partner_phone": payload.get("phone") or False,
            "job_id": job.id,
            "department_id": job.department_id.id,
            "description": payload.get("message") or False,
            "stage_id": stage_id,
            "gr_source_channel": SOURCE_CHANNEL_WEBSITE,
            "gr_external_ref": payload.get("external_ref") or False,
        })

        applicant._gr_store_answers(job, answers)

        if cv:
            applicant._gr_attach(cv, main=True)
        if cover_letter:
            applicant._gr_attach(cover_letter, main=False)

        if plan.get("action") == RULE_ACTION_ARCHIVE:
            # _message_log (et non message_post) : ajoute une note interne SANS
            # notifier de destinataire ni envoyer d'e-mail. message_post
            # declencherait un envoi de mail qui, sans serveur SMTP configure,
            # leve une exception -> reponse d'erreur sans en-tetes CORS ->
            # "Failed to fetch" cote navigateur. L'intake ne doit jamais envoyer.
            applicant._message_log(
                body="Candidature archivee automatiquement (regle de filtre : %s)."
                % (plan.get("reason") or "-")
            )
            applicant.active = False

        _logger.info(
            "GR: candidature %s creee (offre %s, ref %s, action %s)",
            applicant.id, job.id, payload.get("external_ref") or "-",
            plan.get("action") or "none",
        )
        return applicant

    def _gr_store_answers(self, job, answers):
        self.ensure_one()
        Answer = self.env["gr.applicant.answer"]
        questions = {q.id: q for q in job._gr_active_questions()}
        for qid, value in answers.items():
            question = questions.get(qid)
            Answer.create({
                "applicant_id": self.id,
                "question_id": qid if question else False,
                "question_text": question.name if question else "",
                "answer_value": "" if value is None else str(value),
            })

    def _gr_attach(self, doc, main=False):
        self.ensure_one()
        attachment = self.env["ir.attachment"].create({
            "name": doc.get("filename") or ("CV" if main else "Document"),
            "datas": base64.b64encode(doc["content"]),
            "res_model": "hr.applicant",
            "res_id": self.id,
            "mimetype": doc.get("mimetype") or "application/octet-stream",
        })
        if main:
            self.message_main_attachment_id = attachment.id
        return attachment
