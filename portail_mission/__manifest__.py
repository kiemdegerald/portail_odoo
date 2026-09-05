# -*- coding: utf-8 -*-
{
    "name": "Portail Employé — Missions",
    "summary": "Connecteur portail du module Gestion des Missions : "
               "consultation des ordres de mission par les employés.",
    "description": """
Portail Employé — Missions
==========================

Expose le module **Gestion des Missions** aux utilisateurs Portail
(sans licence interne) :

* Carte « Missions » sur l'accueil du portail
* Liste de ses propres demandes de mission
* Détail d'une mission : informations, indemnités, avance, circuit de
  validation

Aucune logique métier ici : ce module n'est qu'un connecteur. Les règles
(circuit, barèmes, numérotation...) vivent dans ``gestion_mission``.
Même principe de sécurité que le module ``portail`` : aucune ACL portail
sur les modèles métier — les contrôleurs restreignent le domaine à
l'employé courant puis lisent en ``sudo()``.
    """,
    "author": "LICELI Technologies",
    "website": "https://www.liceli-technologies.com",
    "category": "Human Resources",
    "version": "17.0.0.28.0",
    "license": "LGPL-3",
    "depends": [
        "portail",
        "gestion_mission",
    ],
    "data": [
        "data/pm_mail_templates.xml",
        "views/portal_templates_mission.xml",
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
}
