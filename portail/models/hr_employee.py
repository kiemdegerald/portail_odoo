# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class HrEmployee(models.Model):
    _inherit = "hr.employee"

    portail_leave_validator_id = fields.Many2one(
        "hr.employee",
        string="Validateur congés",
        help="Employé qui voit et approuve/refuse les demandes de congé de "
             "cet employé sur le portail (page « Congés de mon équipe »). "
             "Remplace le circuit par manager : sans validateur désigné, "
             "personne ne peut statuer sur les demandes de cet employé "
             "depuis le portail.",
    )

    def action_grant_portal_access(self):
        """Provisionne (ou réactive) un utilisateur Portail pour l'employé.

        Le compte est rattaché au *contact professionnel* de l'employé
        (``work_contact_id``) : c'est le lien utilisé par le portail pour
        retrouver les bulletins et congés de la bonne personne.

        Un utilisateur Portail est un utilisateur *partagé* : il ne consomme
        aucune licence interne.

        L'invitation (lien de première connexion) est envoyée **immédiatement**
        (envoi direct, sans passer par la file d'attente des emails), avec un
        objet et un message clairs.
        """
        self.ensure_one()
        partner = self.work_contact_id
        if not partner:
            raise UserError(_(
                "Renseignez d'abord le « Contact professionnel » (adresse) de "
                "l'employé avant d'activer l'accès portail."))
        if not partner.email:
            raise UserError(_(
                "Le contact professionnel de l'employé doit avoir une adresse "
                "email pour recevoir son invitation."))

        Users = self.env["res.users"].sudo()
        portal_group = self.env.ref("base.group_portal")
        user = Users.with_context(active_test=False).search(
            [("partner_id", "=", partner.id)], limit=1)

        # --- Contrôle : l'employé a-t-il DÉJÀ un accès ? ---
        if user and user.active and (
                user.has_group("base.group_portal")
                or user.has_group("base.group_user")):
            if user.login_date:
                # Compte actif et déjà utilisé : ne rien recréer, ne rien renvoyer.
                return self._portal_notification(
                    _("Cet employé a déjà un accès portail (identifiant : "
                      "%(login)s, dernière connexion le %(date)s). Aucun "
                      "nouveau compte n'a été créé.",
                      login=user.login,
                      date=user.login_date.strftime("%d/%m/%Y")),
                    notif_type="warning", sticky=True)
            # Compte créé mais jamais activé : on renvoie juste l'invitation.
            invitation_sent = self._send_portal_invitation(user)
            if invitation_sent:
                message = _(
                    "Cet employé a déjà un compte portail (%(login)s) mais ne "
                    "s'est jamais connecté. Une nouvelle invitation vient de "
                    "lui être envoyée.", login=user.login)
            else:
                message = _(
                    "Cet employé a déjà un compte portail (%(login)s) mais ne "
                    "s'est jamais connecté, et l'envoi de l'invitation a "
                    "échoué. Vérifiez la configuration du serveur de "
                    "messagerie.", login=user.login)
            return self._portal_notification(
                message,
                notif_type="warning" if invitation_sent else "danger",
                sticky=True)

        if user:
            if not user.active:
                user.active = True
            # N'écrase pas un utilisateur interne existant.
            if not user.has_group("base.group_user") and portal_group not in user.groups_id:
                user.write({"groups_id": [(4, portal_group.id)]})
        else:
            # L'email est peut-être déjà l'identifiant d'un compte rattaché à
            # un AUTRE contact (doublon de contact) : créer planterait avec
            # « deux utilisateurs avec le même login ». On explique plutôt.
            conflict = Users.with_context(active_test=False).search(
                [("login", "=ilike", partner.email)], limit=1)
            if conflict:
                return self._portal_notification(
                    _("Impossible de créer le compte : l'identifiant "
                      "%(email)s est déjà utilisé par l'utilisateur "
                      "« %(name)s » (rattaché à un autre contact). Corrigez "
                      "l'adresse email de l'employé ou fusionnez les contacts "
                      "en double.", email=partner.email, name=conflict.name),
                    notif_type="danger", sticky=True)
            user = Users.with_context(no_reset_password=True).create({
                "name": partner.name,
                "login": partner.email,
                "email": partner.email,
                "partner_id": partner.id,
                "company_id": self.company_id.id,
                "company_ids": [(6, 0, self.company_id.ids)],
                "groups_id": [(6, 0, [portal_group.id])],
            })

        # --- Invitation : lien de première connexion, envoi immédiat ---
        invitation_sent = self._send_portal_invitation(user)

        if invitation_sent:
            message = _(
                "Accès portail activé pour %(name)s. Une invitation vient d'être "
                "envoyée à %(email)s.",
                name=partner.name, email=partner.email)
        else:
            message = _(
                "Accès portail activé pour %(name)s, mais l'envoi de l'email "
                "d'invitation a échoué. Vérifiez la configuration du serveur de "
                "messagerie, ou communiquez-lui le lien de connexion manuellement.",
                name=partner.name)

        return self._portal_notification(
            message,
            notif_type="success" if invitation_sent else "warning",
            sticky=not invitation_sent)

    @staticmethod
    def _portal_notification(message, notif_type="info", sticky=False):
        """Notification affichée à l'utilisateur RH après le clic sur le bouton."""
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": notif_type,
                "title": _("Accès portail"),
                "message": message,
                "sticky": sticky,
            },
        }

    def _send_portal_invitation(self, user):
        """Génère le lien de première connexion et envoie l'email tout de suite.

        Retourne True si l'email a bien été expédié (état 'sent').
        """
        self.ensure_one()
        partner = user.partner_id.sudo()
        # Jeton de première connexion (valable par défaut plusieurs jours)
        partner.signup_prepare()
        signup_url = partner.signup_url

        email_from = (
            self.company_id.email
            or self.env.company.email
            or user.login
        )
        body_html = _(
            "<p>Bonjour %(name)s,</p>"
            "<p>Votre <strong>espace personnel</strong> est prêt. Vous pouvez "
            "désormais y accéder pour consulter vos informations et vos "
            "documents à tout moment.</p>"
            "<p>Cliquez sur le bouton ci-dessous pour définir votre mot de passe "
            "et accéder à votre espace :</p>"
            "<p style='margin:16px 0;'>"
            "<a href='%(url)s' "
            "style='background:#714B67;color:#fff;padding:10px 18px;"
            "border-radius:4px;text-decoration:none;'>Activer mon compte</a>"
            "</p>"
            "<p style='color:#888;font-size:12px;'>Si le bouton ne fonctionne "
            "pas, copiez ce lien dans votre navigateur :<br/>%(url)s</p>",
            name=partner.name, url=signup_url,
        )

        mail = self.env["mail.mail"].sudo().create({
            "subject": _("Bienvenue sur votre espace personnel — définissez votre mot de passe"),
            "body_html": body_html,
            "email_from": email_from,
            "email_to": partner.email,
            "auto_delete": False,
        })
        try:
            # Envoi immédiat (ne dépend pas du cron de la file d'attente)
            mail.send(raise_exception=False)
        except Exception:
            return False
        return mail.state == "sent"
