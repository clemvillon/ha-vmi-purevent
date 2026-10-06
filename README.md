# VMI Purevent (VisionAir) pour Home Assistant

Composant personnalisé pour piloter en Bluetooth une VMI Ventilairsec Purevent
(gamme Vision'R, annoncée `VisionAir`) depuis Home Assistant, sans cloud.

Non officiel : sans lien avec Ventilairsec. Vérifié sur une seule machine
(Purevent, logiciel embarqué 6.4.002), à travers un relais Bluetooth ESPHome.

## À savoir avant d'installer

- **La VMI n'accepte qu'une connexion Bluetooth.** Tant que Home Assistant est
  connecté, l'app VMI+ ne peut pas l'être. L'interrupteur « Connexion
  Bluetooth » libère la VMI pour VMI+ ; au retour, Home Assistant relit l'état.
- **Le préchauffage électrique consomme jusqu'à 1 800 W.** Régler une consigne
  le met en marche. Ses commandes sont désactivées d'origine ; ne les activer
  que si cette puissance est mesurée et prise en compte dans l'installation.
- Même domaine (`vmi_plus`) et mêmes identifiants que
  [ha-vmi-plus](https://github.com/srThibaultP/ha-vmi-plus) : ce composant le
  **remplace**, les deux ne s'installent pas ensemble. Les entités existantes
  sont reprises telles quelles.

## Ce qu'il fait

- Connexion permanente ; état, sondes et télécommande relevés toutes les 10 s.
- Entité **Connectée** : liaison ouverte et trame d'état valide reçue depuis
  moins de 35 s. Quand elle s'éteint, toutes les autres entités passent à
  `unavailable` : une perte de liaison se voit.
- L'état affiché vient toujours d'une trame reçue. Une commande n'est tenue
  pour faite que si la VMI la confirme ; sinon, une erreur.
- Les trames dont la somme de contrôle est fausse sont refusées ; une mesure
  isolée aberrante est écartée. Le diagnostic de l'entrée compte les trames
  refusées et garde la dernière, avec son heure et le motif du refus.

| Entité | Type | Rôle |
|---|---|---|
| Vitesse | sélecteur | Faible / Moyenne / Forte |
| Boost | interrupteur | 30 min, minuterie dans la VMI |
| Vacances | interrupteur | allumé tant qu'il reste des jours ; « allumer » pose 1 jour |
| Surventilation | interrupteur | bascule gardée : l'état est relu avant l'envoi |
| Connexion Bluetooth | interrupteur | libère la VMI pour l'app VMI+ |
| Connectée | capteur binaire | état de la liaison |
| Préchauffage en marche, Consigne de préchauffage | lecture | pour voir un préchauffage lancé ailleurs |
| Températures (sonde n°1, entrée d'air), humidité | capteurs | sondes du caisson |
| Filtre, jours restants ; Débit théorique | capteurs | |
| Jours de fonctionnement, Volume, Trame d'état | diagnostic | la trame brute sert à surveiller ce qui n'est pas décodé |
| Vacances (jours) | réglage | 0 à 15 ; 0 = pas de vacances ; le décompte est fait par la VMI |
| Limite d'été | réglage | 22 à 37 °C |
| Débit fixe | interrupteur | réglage d'installation |
| Arrêter le préchauffage | bouton | marche à 0 et consigne à 0 ; ne peut que baisser la puissance |
| Préchauffage (marche), Préchauffage (consigne) | interrupteur, réglage | **désactivés d'origine** ; la consigne (12 à 18 °C) met le préchauffage en marche |

L'horloge de la VMI est mise à l'heure locale à chaque connexion (comme le
fait VMI+), puis à chaque changement d'heure (été, hiver). C'est la seule
écriture faite sans commande.

## Installation (HACS)

HACS → dépôts personnalisés → `https://github.com/clemvillon/ha-vmi-purevent`,
type Intégration → télécharger → redémarrer Home Assistant. La VMI est
proposée par découverte Bluetooth. Aucune dépendance n'est téléchargée : le
composant n'utilise que les bibliothèques Bluetooth fournies par Home
Assistant (vérifié avec la version 2026.9.4).

## Limites connues

- Températures sous 0 °C : lues comme un octet signé, hypothèse non encore
  observée.
- Plages horaires de la VMI : ni lues ni commandées. Les activer dans VMI+ pose
  une consigne de préchauffage, visible ici dans « Consigne de préchauffage ».
- Pourcentage du filtre, qualité d'air : non trouvés dans les trames.

## Tests

Le composant est testé dans Home Assistant contre une capture réelle des
échanges entre l'app VMI+ et la VMI : chaque trame envoyée par l'app est
reconstruite à l'identique, chaque réponse est décodée, et la VMI simulée des
tests est elle-même vérifiée contre cette capture. La capture et les tests
contiennent des données de l'installation d'origine : ils ne sont pas publiés.

## Origine et licence

Licence MIT. Dérivé de [visionair-ble](https://github.com/bartcortooms/visionair-ble)
(Bart Cortooms) pour le protocole et de
[ha-vmi-plus](https://github.com/srThibaultP/ha-vmi-plus) pour la structure du
composant : voir `NOTICE`.
