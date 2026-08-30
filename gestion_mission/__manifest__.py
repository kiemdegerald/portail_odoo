# -*- coding: utf-8 -*-
{
    "name": "Gestion des Missions",
    "summary": "Ordres de mission : demande, circuit de validation, "
               "indemnités journalières et suivi.",
    "description": """
Gestion des Missions
====================

Cycle de vie complet d'une mission professionnelle :

* Demande de mission (objet, destination, zone, dates, transport)
* Circuit de validation configurable à plusieurs niveaux
* Ordre de mission numéroté (PDF)
* Indemnités journalières calculées par barème (zone x catégorie d'agent)
* Avance avant départ et solde au retour
* Piste d'audit complète (exigence de contrôle interne bancaire)

Module métier autonome. L'exposition aux employés (demande et validation
depuis le portail) est assurée par le module compagnon ``portail_mission``.
    """,
    "author": "LICELI Technologies",
    "website": "https://www.liceli-technologies.com",
    "category": "Human Resources",
    "version": "17.0.0.21.0",
    "license": "LGPL-3",
    "depends": [
        "hr",
        "mail",
        "base_setup",
    ],
    "data": [
        "security/gm_security.xml",
        "security/ir.model.access.csv",
        "data/gm_default_data.xml",
        "report/gm_report.xml",
        "report/gm_report_templates.xml",
        "views/gm_validation_views.xml",
        "views/gm_perdiem_views.xml",
        "views/gm_mission_views.xml",
        "views/gm_settings_views.xml",
    ],
    "application": True,
    "installable": True,
    "auto_install": False,
}
