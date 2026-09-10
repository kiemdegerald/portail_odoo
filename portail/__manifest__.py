# -*- coding: utf-8 -*-
{
    "name": "Portail Employé (Self-Service)",
    "summary": "Espace self-service pour les employés via des utilisateurs Portail "
               "(gratuits) : consultation et téléchargement des bulletins de paie, "
               "solde et historique des congés. Architecture extensible.",
    "description": """
Portail Employé
===============

Donne aux employés un accès **Portail** (utilisateurs partagés, sans licence
interne) pour consulter leurs informations RH en libre-service, sans dépendre
du module *Documents* Enterprise.

Sections de cette version
-------------------------
* **Bulletins de paie** : liste, consultation et téléchargement du PDF de ses
  propres bulletins validés.
* **Congés** : solde par type et historique de ses demandes (lecture seule).

Le rattachement employé ↔ utilisateur portail se fait par le *contact
professionnel* (``work_contact_id``). Un bouton « Activer accès portail » est
ajouté sur la fiche employé pour provisionner le compte.

L'architecture (contrôleur ``CustomerPortal`` + templates hérités) est prévue
pour accueillir d'autres sections (contrat, documents, attestations...).
    """,
    "author": "LICELI Technologies",
    "website": "https://www.liceli-technologies.com",
    "category": "Human Resources",
    "version": "17.0.1.12.0",
    "license": "LGPL-3",
    "depends": [
        "portal",
        "website",
        "hr_payroll",
        "hr_holidays",
        "custom_salary_reports",
        # Fournit l'onglet « Documents de congé » (page `leave_documents`)
        # dans lequel views/hr_leave_views.xml place les justificatifs.
        "hr_leave_documents",
    ],
    "data": [
        "data/mail_templates.xml",
        "data/website_page.xml",
        "views/portal_templates_home.xml",
        "views/portal_templates_account.xml",
        "views/portal_templates_payslip.xml",
        "views/portal_templates_leave.xml",
        "views/portal_templates_team.xml",
        "views/hr_employee_views.xml",
        "views/hr_leave_views.xml",
        "views/hr_leave_type_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": True,
    "installable": True,
    "auto_install": False,
}
