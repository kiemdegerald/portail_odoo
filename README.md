# Portail Employé — Odoo 17 (module `portail`)

Espace **self-service RH** pour les employés, via des utilisateurs Portail. Développé par LICELI Technologies.

## Fonctionnalités

### Côté employé
- **Bulletins de paie** : consultation et téléchargement PDF sécurisés
- **Demandes de congé** depuis le site web : types configurables, motif,
  justificatifs multiples (PDF, images, Word — validés par contenu binaire)
- **Suivi complet** : solde par type, historique, modification/annulation
  d'une demande en attente, aperçu et gestion des justificatifs
- **Notifications email** : décision (approuvée/refusée) avec le commentaire
- Page « Mes informations » épurée : identité gérée par les RH,
  suppression de compte désactivée

### Côté validateur
- Champ **« Validateur congés »** sur la fiche employé (indépendant du manager)
- Espace « Congés de mon équipe » : consultation, justificatifs,
  **décision avec commentaire obligatoire**, tracée au chatter
- Notification email à chaque nouvelle demande

### Côté RH / administration
- Types de congé publiés sur le portail par simple case à cocher
  (libellé site personnalisable, autorisation des dates passées par type)
- Adresse de notification RH pilotée par paramètre système
- Modèles d'email modifiables dans l'interface
- Justificatifs visibles dans le backend à tout état de la demande
- Alerte calendrier : participant invité déjà en congé approuvé

## Sécurité
- Rattachement employé ↔ compte portail par le contact professionnel ;
  lectures `sudo()` uniquement après restriction du domaine (aucune ACL RH ouverte)
- Anti-usurpation : chacun ne soumet que pour lui-même
- Fichiers validés par **signature binaire** (jamais par extension) ;
  aperçu inline limité aux formats sûrs (anti-XSS stocké)
- Verrous serveur systématiques derrière chaque restriction d'interface

## Architecture
```
portail/
├── controllers/
│   ├── portal_common.py     # socle partagé (sécurité, helpers)
│   ├── portal_payslip.py    # bulletins
│   ├── portal_leave.py      # congés employé
│   ├── portal_team.py       # espace validateur
│   ├── portal_account.py    # mes informations
│   └── website_form.py      # formulaire du site
├── models/                  # hr.employee, hr.leave, hr.leave.type, ...
├── views/                   # un fichier de templates par domaine
└── data/                    # page website embarquée, modèles d'email
```
Conçu comme **socle d'une famille de modules** : les domaines suivants
(missions, évaluations...) s'ajoutent en modules séparés dépendant de celui-ci.

## Installation
1. Placer `portail/` dans le `addons_path`
2. Installer le module (la page web, le menu et les réglages par défaut
   sont créés automatiquement)
3. Configurer : adresse RH (`portail.email_notification_rh`), types de
   congé à publier, validateurs sur les fiches employés

**Prérequis** : Odoo 17 Enterprise (hr_payroll), modules `hr_leave_documents`
et `custom_salary_reports` de l'écosystème LICELI.

## Modules missions (même écosystème)

- **`gestion_mission`** (module métier autonome) : demandes de mission,
  circuit de validation configurable photographié à la soumission,
  numérotation officielle NNN/AAAA/SIGLE à la validation, barèmes per
  diem par zone × catégorie d'agent, avance paramétrable et solde,
  frais à justifier multi-lignes, ordre de mission et fiche de décompte
  PDF, écran de paramètres dédié.
- **`portail_mission`** (connecteur portail, dépend de `portail` et
  `gestion_mission`) : l'employé consulte, crée, soumet, corrige et
  retire ses demandes ; le valideur statue (approbation, refus, renvoi
  commenté) ; notifications email à chaque étape ; téléchargement des
  documents officiels des missions validées. Aucune logique métier dans
  le connecteur.

## Module recrutement (même écosystème)

- **`gestion_recrutement`** (dépend du Recrutement standard d'Odoo) :
  passerelle HTTP entre le site web externe et Odoo — diffusion des
  offres publiées, réception des candidatures avec CV injectées dans le
  pipeline standard. API protégée par clé (paramètre système, jamais
  dans le code), limitation de débit, création automatique de l'employé
  à l'embauche (paramétrable).

### Cycle de vie complet d'une mission

Demande -> circuit de validation -> ordre de mission numéroté -> avance
-> **retour déclaré** (dates réelles, note de frais justifiée, décompte
recalculé) -> règlement du solde -> **clôture**. Annulation possible
avec motif obligatoire, numéro conservé. Missions individuelles ou
groupées (indemnité propre à chaque missionnaire).

## Module évaluation (même écosystème)

- **`gestion_evaluation`** (complète le module *Évaluations* standard
  d'Odoo) : campagnes annuelles avec ciblage d'une population et
  génération en masse, circuit à plusieurs phases dont la validation
  N+2, objectifs rattachés à leur exercice, et **grille de notation
  configurable** — blocs, thèmes, critères, sans pondération : la note
  d'un thème est la moyenne de ses critères, celle d'un bloc la moyenne
  de ses thèmes, la note globale la moyenne des blocs, exactement comme
  la fiche d'appréciation de la banque. Exports Excel de la fiche d'un
  agent et du récapitulatif de campagne.
