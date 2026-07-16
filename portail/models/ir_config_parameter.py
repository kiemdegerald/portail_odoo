# -*- coding: utf-8 -*-
import re

from odoo import api, models

# Paramètre système : adresse RH destinataire des notifications du
# formulaire de demande de congés (modifiable via Paramètres > Technique >
# Paramètres système, sans redéploiement).
PARAM_EMAIL_RH = "portail.email_notification_rh"


class IrConfigParameter(models.Model):
    _inherit = "ir.config_parameter"

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if any(vals.get("key") == PARAM_EMAIL_RH for vals in vals_list):
            self._portail_sync_leave_form_email()
        return records

    def write(self, vals):
        keys = set(self.mapped("key"))
        if vals.get("key"):
            keys.add(vals["key"])
        res = super().write(vals)
        if PARAM_EMAIL_RH in keys:
            self._portail_sync_leave_form_email()
        return res

    def _portail_sync_leave_form_email(self):
        """Recopie le paramètre dans le champ caché ``email_to`` du
        formulaire de la page /demande-de-conges (toutes les langues).

        L'email doit rester un attribut STATIQUE de la page : la signature
        anti-falsification d'Odoo (``website.tools.add_form_signature``) est
        calculée sur l'ARCH de la vue, pas sur son rendu — un ``t-att-value``
        dynamique ferait signer une autre valeur et toute soumission serait
        rejetée (AccessDenied). D'où cette synchronisation à l'écriture du
        paramètre : la page est réécrite, et Odoo re-signe correctement.
        """
        email = (self.sudo().get_param(PARAM_EMAIL_RH) or "").strip()
        view = self.env.ref("portail.view_demande_de_conges",
                            raise_if_not_found=False)
        if not email or not view:
            return
        view = view.sudo()
        self.env.cr.execute(
            "SELECT jsonb_object_keys(arch_db) FROM ir_ui_view WHERE id=%s",
            (view.id,))
        for (lang,) in self.env.cr.fetchall():
            view_lang = view.with_context(lang=lang)
            arch = view_lang.arch_db
            new_arch = re.sub(
                r'(name="email_to" value=")[^"]*(")',
                lambda m: m.group(1) + email + m.group(2),
                arch)
            if new_arch != arch:
                view_lang.write({"arch_db": new_arch})
