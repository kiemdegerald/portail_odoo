# -*- coding: utf-8 -*-
"""Briques COMMUNES de l'espace portail employé.

Ce fichier ne déclare aucune route : il porte les constantes, la validation
des justificatifs et la classe de base ``PortailCommon`` dont héritent les
contrôleurs par domaine (paie, congés, validateur, compte). Les futurs
modules (portail_missions, portail_evaluations...) peuvent réutiliser ces
briques de la même façon.

Principe de sécurité central : le rattachement utilisateur portail -> employé
se fait par le contact professionnel (``work_contact_id``) — c'est ce même
partenaire qui porte le compte utilisateur portail. Toutes les lectures se
font en ``sudo()`` APRÈS avoir restreint le domaine à l'employé courant, ce
qui évite d'ouvrir des droits d'accès (ACL) sur les modèles RH.
"""
import base64
from contextlib import contextmanager

from odoo import _
from odoo.http import request
from odoo.exceptions import MissingError, ValidationError
from odoo.tools.mimetypes import guess_mimetype, _check_ooxml
from odoo.addons.portal.controllers.portal import CustomerPortal

# États d'un bulletin visibles par l'employé (bulletins finalisés uniquement)
PAYSLIP_VISIBLE_STATES = ("done", "paid")

# Libellés FR des statuts de congé (hr.leave.state)
LEAVE_STATE_LABELS = {
    "draft": "À soumettre",
    "confirm": "À approuver",
    "refuse": "Refusé",
    "validate1": "2ᵉ approbation",
    "validate": "Approuvé",
}

# États d'une demande de congé encore modifiable/annulable par l'employé
# (tant qu'elle n'a pas été approuvée ni refusée).
LEAVE_EDITABLE_STATES = ("draft", "confirm")

# États d'une demande de congé sur lesquels un validateur peut agir
LEAVE_APPROVABLE_STATES = ("confirm",)

# Justificatifs : formats autorisés (validés sur le CONTENU du fichier, pas
# son extension) et taille maximale.
JUSTIFICATIF_MAX_SIZE = 5 * 1024 * 1024  # 5 Mo
JUSTIFICATIF_ALLOWED_MIMETYPES = (
    "application/pdf",
    "image/jpeg",
    "image/png",
    # Word (.doc / .docx) — détectés par signature binaire (OLE / OOXML)
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
)
# Seuls ces formats sont servis en aperçu « inline » : tout autre contenu
# rendu par le navigateur (HTML, SVG...) ouvrirait un vol de session (XSS
# stocké). Word est donc accepté à l'upload mais servi en téléchargement.
JUSTIFICATIF_INLINE_MIMETYPES = (
    "application/pdf",
    "image/jpeg",
    "image/png",
)


def detect_justificatif_mimetype(content):
    """Mimetype détecté depuis le contenu binaire.

    Un ``.docx`` est un zip : selon la version de libmagic, il peut être
    détecté comme simple ``application/zip`` — on affine alors avec
    l'inspection OOXML d'Odoo (liste des entrées du zip).
    """
    mimetype = guess_mimetype(content or b"")
    if mimetype == "application/zip":
        try:
            mimetype = _check_ooxml(content) or mimetype
        except Exception:
            pass
    return mimetype


def validate_justificatif(filename, content):
    """Valide un justificatif uploadé et retourne son mimetype détecté.

    Le type est détecté depuis le contenu binaire : un fichier HTML renommé
    « certificat.pdf » est rejeté. Lève ``ValidationError`` (message clair
    affiché à l'utilisateur) si le format n'est pas autorisé ou si le fichier
    dépasse la taille maximale.
    """
    filename = filename or _("fichier")
    if not content:
        raise ValidationError(_("Le fichier « %s » est vide.", filename))
    if len(content) > JUSTIFICATIF_MAX_SIZE:
        raise ValidationError(_(
            "Le fichier « %s » dépasse la taille maximale autorisée (5 Mo).",
            filename))
    mimetype = detect_justificatif_mimetype(content)
    if mimetype not in JUSTIFICATIF_ALLOWED_MIMETYPES:
        raise ValidationError(_(
            "Format non autorisé pour « %s ». Formats acceptés : PDF, JPEG, "
            "PNG, Word (DOC/DOCX).", filename))
    return mimetype


class PortailCommon(CustomerPortal):
    """Base commune des contrôleurs du portail (aucune route ici)."""

    # ------------------------------------------------------------------
    # Écriture d'un formulaire : tout ou rien
    # ------------------------------------------------------------------
    @contextmanager
    def _ecriture_atomique(self):
        """Annule TOUT ce qu'un formulaire a écrit dès qu'il est refusé.

        Un contrôleur de portail attrape ``UserError``/``ValidationError``
        pour réafficher la page avec le message : c'est le bon geste côté
        écran, mais il a un effet de bord que rien ne signale. En temps
        normal, l'exception remonte jusqu'à la couche HTTP d'Odoo, qui
        annule la transaction ; attrapée ici, elle ne remonte plus, la
        requête se termine normalement — et Odoo VALIDE ce que le
        formulaire avait déjà écrit avant de buter.

        Concrètement, sur une fiche d'évaluation : les taux des premières
        activités partaient en base, la note fautive arrêtait le reste, et
        l'écran affichait « refusé » sur une fiche à moitié modifiée. Pire,
        une valeur hors barème pouvait rester enregistrée : le contrôle de
        cohérence s'exécute APRÈS l'UPDATE, et c'est le rollback — celui
        qu'on venait de neutraliser — qui devait l'effacer.

        On enveloppe donc toute écriture de formulaire dans un point de
        reprise : à la moindre erreur, la base revient exactement à son
        état d'avant, puis l'exception poursuit sa route vers le
        ``except`` du contrôleur, qui affiche le message. Le cache de
        l'ORM est vidé au passage, sans quoi la page réaffichée
        montrerait des valeurs qui n'existent plus.
        """
        try:
            with request.env.cr.savepoint():
                yield
        except Exception:
            request.env.invalidate_all()
            raise

    # ------------------------------------------------------------------
    # Résolution employé / périmètre du validateur
    # ------------------------------------------------------------------
    def _get_portal_employees(self):
        """Employé(s) rattaché(s) à l'utilisateur portail connecté."""
        partner = request.env.user.partner_id
        Employee = request.env["hr.employee"].sudo()
        if not partner:
            return Employee
        return Employee.search([("work_contact_id", "=", partner.id)])

    def _get_managed_employees(self):
        """Employés dont l'utilisateur portail connecté est le « Validateur
        congés » (``portail_leave_validator_id`` de la fiche employé).

        Depuis le 2026-07-16, l'approbation ne passe PLUS par le manager
        (``parent_id``) : seul le validateur désigné voit et traite les
        demandes de l'employé sur le portail."""
        employees = self._get_portal_employees()
        Employee = request.env["hr.employee"].sudo()
        if not employees:
            return Employee
        return Employee.search(
            [("portail_leave_validator_id", "in", employees.ids)])

    # ------------------------------------------------------------------
    # Pièces jointes (justificatifs) d'une demande de congé
    # ------------------------------------------------------------------
    def _get_leave_attachments(self, leave):
        """Justificatifs rattachés à une demande de congé."""
        return request.env["ir.attachment"].sudo().search([
            ("res_model", "=", "hr.leave"),
            ("res_id", "=", leave.id),
        ], order="id")

    def _attach_leave_file(self, leave, file_storage):
        """Rattache un fichier uploadé (werkzeug FileStorage) à la demande.

        Le fichier est validé (format détecté sur le contenu, taille max) et
        le mimetype STOCKÉ est celui détecté — jamais celui annoncé par le
        client.
        """
        if not (file_storage and getattr(file_storage, "filename", "")):
            return False
        content = file_storage.read() or b""
        mimetype = validate_justificatif(file_storage.filename, content)
        return request.env["ir.attachment"].sudo().create({
            "name": file_storage.filename,
            "datas": base64.b64encode(content),
            "mimetype": mimetype,
            "res_model": "hr.leave",
            "res_id": leave.id,
        })

    def _get_leave_attachment_or_raise(self, leave, attachment_id):
        """La pièce jointe, après vérification qu'elle appartient à la demande."""
        attachment = request.env["ir.attachment"].sudo().browse(attachment_id).exists()
        if not attachment or attachment.res_model != "hr.leave" \
                or attachment.res_id != leave.id:
            raise MissingError(_("Pièce jointe introuvable."))
        return attachment

    def _serve_leave_attachment(self, leave, attachment_id, inline=False):
        """Réponse HTTP d'un justificatif de la demande.

        ``inline=True`` : affichage direct dans le navigateur — accordé
        UNIQUEMENT aux formats sûrs (PDF/images) ; tout autre contenu (ex.
        pièce historique uploadée avant la validation des formats) est servi
        en téléchargement forcé, en ``application/octet-stream``, pour que le
        navigateur ne puisse jamais l'exécuter. L'appartenance de la demande
        au user courant (ou à son périmètre de validateur) doit avoir été
        contrôlée AVANT ; ici on vérifie seulement que la pièce jointe
        appartient bien à cette demande.
        """
        attachment = self._get_leave_attachment_or_raise(leave, attachment_id)
        content = base64.b64decode(attachment.datas or b"")
        # Le mimetype servi est re-détecté depuis le contenu : le mimetype
        # stocké peut avoir été forgé (enregistrement créé en sudo).
        mimetype = detect_justificatif_mimetype(content)
        if mimetype not in JUSTIFICATIF_INLINE_MIMETYPES:
            inline = False
        if mimetype not in JUSTIFICATIF_ALLOWED_MIMETYPES:
            mimetype = "application/octet-stream"
        disposition = "inline" if inline else "attachment"
        filename = (attachment.name or "justificatif")
        filename = "".join(c for c in filename if c not in '"\r\n')
        headers = [
            ("Content-Type", mimetype),
            ("Content-Length", len(content)),
            ("Content-Disposition", '%s; filename="%s"' % (disposition, filename)),
            ("X-Content-Type-Options", "nosniff"),
        ]
        return request.make_response(content, headers=headers)

    # ------------------------------------------------------------------
    # Page d'accueil /my : drapeau validateur + compteurs des cartes
    # ------------------------------------------------------------------
    def _payslip_domain(self, employees):
        # Ici (et pas dans portal_payslip.py) car le compteur de la carte
        # d'accueil en a aussi besoin.
        return [
            ("employee_id", "in", employees.ids),
            ("state", "in", list(PAYSLIP_VISIBLE_STATES)),
        ]

    def _prepare_portal_layout_values(self):
        """Ajoute le drapeau validateur, utilisé pour afficher la carte
        « Congés de mon équipe » sur la page d'accueil du portail."""
        values = super()._prepare_portal_layout_values()
        values["portail_is_manager"] = bool(self._get_managed_employees())
        return values

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        employees = self._get_portal_employees()
        if "payslip_count" in counters:
            values["payslip_count"] = request.env["hr.payslip"].sudo().search_count(
                self._payslip_domain(employees)
            ) if employees else 0
        if "leave_count" in counters:
            values["leave_count"] = request.env["hr.leave"].sudo().search_count(
                [("employee_id", "in", employees.ids)]
            ) if employees else 0
        if "team_leave_count" in counters:
            managed = self._get_managed_employees()
            values["team_leave_count"] = request.env["hr.leave"].sudo().search_count(
                [("employee_id", "in", managed.ids),
                 ("state", "in", list(LEAVE_APPROVABLE_STATES))]
            ) if managed else 0
        return values
