# -*- coding: utf-8 -*-
{
    "name": "Portail Employé — Évaluations",
    "summary": "Connecteur portail du module Gestion des Évaluations : "
               "auto-évaluation et consultation de son entretien annuel.",
    "description": """
Portail Employé — Évaluations
=============================

Expose les évaluations aux utilisateurs **Portail** (sans licence
interne), comme l'exige le cahier des charges de la banque (« accès
sécurisé aux évaluations ») :

* carte « Mes évaluations » sur l'accueil du portail ;
* consultation de son évaluation : campagne, phase en cours, objectifs ;
* **auto-évaluation** : l'agent remplit sa colonne de la grille, ajoute
  son commentaire, puis publie ;
* après publication du manager, la note et l'appréciation de celui-ci
  s'affichent en regard des siennes.

Aucune logique métier ici : ce module n'est qu'un connecteur. Les
règles (qui note quoi, quand, ce qui est visible) vivent dans
``gestion_evaluation``. Même principe de sécurité que le module
``portail`` : aucune ACL portail sur les modèles métier — les
contrôleurs restreignent le domaine à l'employé courant puis lisent en
``sudo()``.
    """,
    "author": "LICELI Technologies",
    "website": "https://www.liceli-technologies.com",
    "category": "Human Resources",
    "version": "17.0.0.19.0",
    "license": "LGPL-3",
    "depends": [
        "portail",
        "gestion_evaluation",
    ],
    "data": [
        "views/portal_templates_evaluation.xml",
    ],
    "application": False,
    "installable": True,
    "auto_install": False,
}
