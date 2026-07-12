# -*- coding: utf-8 -*-
import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class HrLeave(models.Model):
    _inherit = "hr.leave"

    portail_decision_note = fields.Text(
        string="Commentaire de décision (portail)",
        help="Raison saisie par le manager au moment d'approuver ou de refuser "
             "la demande depuis le portail. Visible par l'employé sur son "
             "portail et par les RH dans Odoo.",
    )

    # ------------------------------------------------------------------
    # Emails du circuit d'approbation
    # ------------------------------------------------------------------
    def _portail_send_template(self, xmlid):
        """Envoie un modèle d'email pour cette demande, SANS JAMAIS bloquer
        le flux métier : tout échec (modèle supprimé, serveur mail en panne,
        adresse invalide...) est simplement journalisé. Règle du projet :
        la création/décision d'une demande ne doit pas dépendre du mail."""
        self.ensure_one()
        template = self.env.ref(xmlid, raise_if_not_found=False)
        if not template:
            _logger.warning("Portail: modèle d'email %s introuvable "
                            "(demande %s, aucun envoi)", xmlid, self.id)
            return
        try:
            # Expéditeur explicite : l'envoi est exécuté par le superuser
            # (OdooBot), dont l'adresse par défaut (odoobot@example.com)
            # serait rejetée/spammée par les messageries. On force l'adresse
            # d'expédition configurée (paramètre standard mail.default.from,
            # aligné sur le compte SMTP), sinon celle de la société.
            email_from = (self.env["ir.mail_server"]._get_default_from_address()
                          or self.company_id.email)
            email_values = {"email_from": email_from} if email_from else None
            template.sudo().send_mail(
                self.id, force_send=True, raise_exception=False,
                email_values=email_values)
        except Exception:
            _logger.exception(
                "Portail: échec d'envoi de l'email %s pour la demande %s",
                xmlid, self.id)

    def _portail_notify_validator(self):
        """Prévient le « Validateur congés » qu'une demande vient d'être
        soumise depuis le portail (ou l'informe, si type auto-validé)."""
        for leave in self:
            if leave.employee_id.portail_leave_validator_id.work_email:
                leave._portail_send_template(
                    "portail.mail_template_leave_submitted")

    def _portail_notify_employee_decision(self):
        """Prévient l'employé que sa demande a été approuvée/refusée
        depuis le portail (avec le commentaire du validateur)."""
        for leave in self:
            if leave.employee_id.work_email:
                leave._portail_send_template(
                    "portail.mail_template_leave_decided")
