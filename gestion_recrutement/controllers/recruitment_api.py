# -*- coding: utf-8 -*-
"""Passerelles HTTP entre le site web externe et Odoo.

Controleur volontairement mince : il gere uniquement le transport
(authentification, CORS, anti-spam, parsing, codes HTTP, JSON) et delegue
toute la logique metier aux modeles hr.job et hr.applicant.
"""
import base64
import hmac
import json
import logging
import time
from collections import defaultdict

from odoo import http, SUPERUSER_ID
from odoo.http import request

from odoo.addons.gestion_recrutement.const import (
    ALLOWED_DOC_MIMETYPES,
    API_USER_XMLID,
    MAX_DOC_SIZE,
    PARAM_API_KEY,
    PARAM_CORS_ORIGIN,
    PARAM_ENABLED,
    PARAM_RATE_LIMIT_MAX,
    PARAM_RATE_LIMIT_WINDOW,
    RATE_LIMIT_MAX,
    RATE_LIMIT_WINDOW,
    RULE_ACTION_BLOCK,
)

_logger = logging.getLogger(__name__)

ERROR_MESSAGES = {
    "service_disabled": "Le service d'integration est desactive.",
    "unauthorized": "Cle API absente ou invalide.",
    "rate_limited": "Trop de requetes. Merci de reessayer dans un instant.",
    "missing_fields": "Des champs obligatoires sont manquants.",
    "invalid_job": "Offre inexistante ou non publiee.",
    "not_found": "Ressource introuvable.",
    "file_too_large": "Fichier trop volumineux (maximum 5 Mo).",
    "invalid_file_type": "Type de fichier non autorise (PDF, DOC ou DOCX).",
    "invalid_answers": "Le format des reponses aux questions est invalide.",
    "missing_required_answers": "Des questions obligatoires n'ont pas de reponse.",
    "application_rejected": "Votre candidature ne remplit pas les criteres requis.",
}


class GestionRecrutementApiController(http.Controller):

    _rate_buckets = defaultdict(list)

    def _param(self, key, default=""):
        return request.env["ir.config_parameter"].sudo().get_param(key, default)

    def _int_param(self, key, default):
        try:
            return int(self._param(key, default))
        except (TypeError, ValueError):
            return default

    def _is_enabled(self):
        return self._param(PARAM_ENABLED, "0") in ("1", "True", "true")

    def _check_api_key(self):
        provided = request.httprequest.headers.get("X-API-Key", "")
        expected = self._param(PARAM_API_KEY, "")
        if not expected or not provided:
            return False
        return hmac.compare_digest(str(provided), str(expected))

    def _cors_headers(self):
        origin = self._param(PARAM_CORS_ORIGIN, "*") or "*"
        return [
            ("Access-Control-Allow-Origin", origin),
            ("Access-Control-Allow-Methods", "GET, POST, OPTIONS"),
            ("Access-Control-Allow-Headers", "Content-Type, X-API-Key"),
            ("Access-Control-Max-Age", "86400"),
            ("Vary", "Origin"),
        ]

    def _json(self, payload, status=200):
        return request.make_json_response(
            payload, status=status, headers=self._cors_headers())

    def _error(self, code, status, **extra):
        payload = {"error": code, "message": ERROR_MESSAGES.get(code, code)}
        payload.update(extra)
        return self._json(payload, status=status)

    def _api_env(self):
        try:
            api_user = request.env.ref(API_USER_XMLID)
            return request.env(user=api_user.id)
        except Exception:
            # Si l'XML-ID de l'utilisateur technique n'existe pas (install partielle,
            # base migrée, ou installation manquante), on tombe en fallback vers
            # l'utilisateur superuser (id=SUPERUSER_ID) pour éviter une exception
            # 500 côté contrôleur. Idéalement, l'utilisateur technique doit exister
            # (voir `gr_security.xml`).
            _logger.warning("GR: API user '%s' introuvable → fallback vers SUPERUSER_ID", API_USER_XMLID)
            return request.env(user=SUPERUSER_ID)

    def _client_ip(self):
        fwd = request.httprequest.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.httprequest.remote_addr or "unknown"

    def _rate_limited(self):
        max_req = self._int_param(PARAM_RATE_LIMIT_MAX, RATE_LIMIT_MAX)
        window = self._int_param(PARAM_RATE_LIMIT_WINDOW, RATE_LIMIT_WINDOW)
        now = time.time()
        ip = self._client_ip()
        recent = [t for t in self._rate_buckets[ip] if now - t < window]
        recent.append(now)
        self._rate_buckets[ip] = recent
        return len(recent) > max_req

    def _guard(self, throttle=False):
        if not self._is_enabled():
            return self._error("service_disabled", 503)
        if not self._check_api_key():
            return self._error("unauthorized", 401)
        if throttle and self._rate_limited():
            return self._error("rate_limited", 429)
        return None

    def _validate_upload(self, upload):
        content = upload.read()
        if len(content) > MAX_DOC_SIZE:
            return None, self._error("file_too_large", 413)
        if upload.mimetype not in ALLOWED_DOC_MIMETYPES:
            return None, self._error("invalid_file_type", 415)
        return {
            "filename": upload.filename,
            "content": content,
            "mimetype": upload.mimetype,
        }, None

    @http.route(
        [
            "/api/recruitment/jobs",
            "/api/recruitment/applications",
            "/api/recruitment/jobs/<int:job_id>/documents/<int:att_id>",
        ],
        type="http", auth="public", methods=["OPTIONS"], csrf=False,
    )
    def cors_preflight(self, **kwargs):
        return request.make_response("", status=204, headers=self._cors_headers())

    @http.route(
        "/api/recruitment/jobs",
        type="http", auth="public", methods=["GET"], csrf=False,
    )
    def list_jobs(self, **kwargs):
        guard = self._guard()
        if guard:
            return guard
        env = self._api_env()
        jobs = env["hr.job"].get_gr_published_jobs()
        return self._json({"jobs": [job.gr_serialize() for job in jobs]})

    @http.route(
        "/api/recruitment/jobs/<int:job_id>/documents/<int:att_id>",
        type="http", auth="public", methods=["GET"], csrf=False,
    )
    def get_job_document(self, job_id, att_id, **kwargs):
        guard = self._guard()
        if guard:
            return guard
        env = self._api_env()
        job = env["hr.job"].browse(job_id).exists()
        if not job or not job.gr_is_published:
            return self._error("not_found", 404)
        att = env["ir.attachment"].browse(att_id).exists()
        if not att or att.res_model != "hr.job" or att.res_id != job_id:
            return self._error("not_found", 404)
        content = base64.b64decode(att.datas or b"")
        headers = self._cors_headers() + [
            ("Content-Type", att.mimetype or "application/octet-stream"),
            ("Content-Disposition",
             'attachment; filename="%s"' % (att.name or "document")),
        ]
        return request.make_response(content, headers=headers)

    def _parse_answers(self, raw):
        if not raw:
            return {}, None
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return None, "invalid_answers"
        result = {}
        try:
            if isinstance(data, dict):
                for k, v in data.items():
                    result[int(k)] = v
            elif isinstance(data, list):
                for item in data:
                    result[int(item["question_id"])] = item.get("value")
            else:
                return None, "invalid_answers"
        except (KeyError, TypeError, ValueError):
            return None, "invalid_answers"
        return result, None

    @http.route(
        "/api/recruitment/applications",
        type="http", auth="public", methods=["POST"], csrf=False,
    )
    def create_application(self, **post):
        guard = self._guard(throttle=True)
        if guard:
            return guard

        # Lire les fichiers televerses immediatement, avant tout retour anticipe.
        # Le corps de la requete doit toujours etre entierement consomme, meme
        # si l'on repond tot (doublon, refus par regle, reponses obligatoires
        # manquantes). Sinon werkzeug ferme la connexion (Connection: close)
        # pendant que le navigateur envoie encore le fichier, ce qui se traduit
        # cote client par "Failed to fetch" au lieu de recevoir la reponse JSON.
        cv = cover = None
        cv_err = cover_err = None
        cv_upload = request.httprequest.files.get("cv")
        if cv_upload and cv_upload.filename:
            cv, cv_err = self._validate_upload(cv_upload)
        lm_upload = request.httprequest.files.get("cover_letter")
        if lm_upload and lm_upload.filename:
            cover, cover_err = self._validate_upload(lm_upload)

        payload = {
            "name": (post.get("name") or "").strip(),
            "email": (post.get("email") or "").strip(),
            "phone": (post.get("phone") or "").strip(),
            "message": post.get("message") or "",
            "external_ref": (post.get("external_ref") or "").strip(),
        }

        missing = [f for f in ("job_id", "name", "email")
                   if not (post.get(f) or "").strip()]
        if missing:
            return self._error("missing_fields", 400, fields=missing)

        try:
            job_id = int(post.get("job_id"))
        except (TypeError, ValueError):
            return self._error("invalid_job", 400)

        env = self._api_env()
        job = env["hr.job"].browse(job_id).exists()
        if not job or not job.gr_is_published:
            return self._error("invalid_job", 404)

        Applicant = env["hr.applicant"]
        existing = Applicant._gr_find_by_external_ref(payload["external_ref"])
        if existing:
            return self._json(
                {"status": "duplicate", "application_id": existing.id}, status=200)

        answers, err = self._parse_answers(post.get("answers"))
        if err:
            return self._error(err, 400)

        missing_q = job.gr_missing_required(answers)
        if missing_q:
            return self._error(
                "missing_required_answers", 400, questions=missing_q)

        plan = job.gr_evaluate_answers(answers)
        if plan.get("action") == RULE_ACTION_BLOCK:
            _logger.info(
                "GR: candidature refusee (offre %s, regle %s)",
                job.id, plan.get("reason") or "-")
            return self._json(
                {"status": "rejected", "reason": plan.get("reason"),
                 "message": ERROR_MESSAGES["application_rejected"]},
                status=200)

        # Les erreurs de fichier (taille/type) ne sont renvoyees qu'ici, une fois
        # passes les cas de refus/doublon : le fichier a deja ete lu plus haut
        # (corps draine), on ne fait que retourner l'erreur eventuelle.
        if cv_err:
            return cv_err
        if cover_err:
            return cover_err

        applicant = Applicant.create_from_website(
            job, payload, answers=answers, plan=plan, cv=cv, cover_letter=cover)

        archived = plan.get("action") == "archive"
        return self._json(
            {"status": "created", "application_id": applicant.id,
             "archived": archived},
            status=201)
