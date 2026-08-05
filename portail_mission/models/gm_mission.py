# -*- coding: utf-8 -*-
"""Notifications email du circuit des missions.

Elles vivent dans le CONNECTEUR (et pas dans gestion_mission) car les
emails pointent vers les pages du portail. Même règle que le module
portail : un échec d'email ne bloque JAMAIS le flux métier. Les
notifications partent quelle que soit l'origine de l'action (portail ou
backend) : le circuit est le même.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class GmMission(models.Model):
    _inherit = "gm.mission"

    # ------------------------------------------------------------------
    # Envoi générique (copié du pattern éprouvé du module portail)
    # ------------------------------------------------------------------
    def _pm_send_template(self, xmlid, email_to=None):
        """Envoie un modèle d'email pour cette mission, sans jamais
        bloquer le flux métier : tout échec est simplement journalisé.
        ``email_to`` force le destinataire (envois par membre)."""
        self.ensure_one()
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if not template:
            _logger.warning("Portail missions : modèle %s introuvable "
                            "(mission %s, aucun envoi)", xmlid, self.id)
            return
        try:
            # Expéditeur explicite : l'envoi s'exécute souvent en sudo
            # (OdooBot), dont l'adresse par défaut serait rejetée/spammée.
            email_from = (
                self.env["ir.mail_server"]._get_default_from_address()
                or self.company_id.email)
            email_values = {}
            if email_from:
                email_values["email_from"] = email_from
            if email_to:
                email_values["email_to"] = email_to
            template.sudo().send_mail(
                self.id, force_send=True, raise_exception=False,
                email_values=email_values or None)
        except Exception:
            _logger.exception(
                "Portail missions : échec d'envoi de l'email %s pour la "
                "mission %s", xmlid, self.id)

    @staticmethod
    def _pm_employee_email(employee):
        return employee.work_contact_id.email or employee.work_email

    def _pm_notify_current_validator(self):
        """Prévient le valideur de l'étape EN COURS qu'une décision est
        attendue de lui."""
        for mission in self:
            validator = mission.current_validator_id
            if validator and mission._pm_employee_email(validator):
                mission._pm_send_template(
                    "portail_mission.mail_mission_to_validate")

    def _pm_notify_employee(self, xmlid):
        for mission in self:
            if mission._pm_employee_email(mission.employee_id):
                mission._pm_send_template(xmlid)

    def _pm_notify_membres(self, xmlid):
        """Un email PAR MEMBRE de la mission (chacun est concerné —
        ex. mission validée), salutation nominative via le contexte."""
        for mission in self:
            for membre in mission.membre_ids:
                email = mission._pm_employee_email(membre.employee_id)
                if email:
                    mission.with_context(
                        pm_recipient_name=membre.employee_id.name,
                    )._pm_send_template(xmlid, email_to=email)

    # ------------------------------------------------------------------
    # Déclencheurs : après chaque action du cycle de vie
    # ------------------------------------------------------------------
    def action_submit(self):
        res = super().action_submit()
        self._pm_notify_current_validator()
        return res

    def action_approve_step(self, comment=None):
        res = super().action_approve_step(comment=comment)
        for mission in self:
            if mission.state == "submitted":
                # étape suivante activée -> prévenir son valideur
                mission._pm_notify_current_validator()
            elif mission.state == "validated":
                # tous les membres sont informés, pas seulement le chef
                mission._pm_notify_membres(
                    "portail_mission.mail_mission_validated")
        return res

    def action_refuse_step(self, comment=None):
        res = super().action_refuse_step(comment=comment)
        self._pm_notify_employee("portail_mission.mail_mission_refused")
        return res

    def action_send_back(self, comment=None):
        res = super().action_send_back(comment=comment)
        # le commentaire n'est pas stocké sur la mission (il est au
        # chatter) : on le transmet au rendu du modèle via le contexte.
        self.with_context(pm_comment=comment or "")._pm_notify_employee(
            "portail_mission.mail_mission_sent_back")
        return res
