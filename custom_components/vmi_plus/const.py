"""Constantes du composant VMI Purevent (domaine vmi_plus).

Toutes les valeurs du composant sont nommées ici ou dans protocol.py (ce qui
relève du protocole). Aucune n'est un réglage d'utilisateur.
"""

DOMAIN = "vmi_plus"
MANUFACTURER = "Ventilairsec"
MODEL = "VMI Purevent"

# Bluetooth : services et caractéristiques annoncés par la VMI.
SERVICE_COMMANDE_UUID = "0003cbbb-0000-1000-8000-00805f9b0131"
CARAC_COMMANDE_UUID = "0003cbb1-0000-1000-8000-00805f9b0131"
SERVICE_TELEMESURE_UUID = "0003cab5-0000-1000-8000-00805f9b0131"
CARAC_TELEMESURE_UUID = "0003caa2-0000-1000-8000-00805f9b0131"

# Rythme. VMI+ relève elle aussi l'état toutes les 10 s.
RELEVE_S = 10  # entre deux tours de relevé, et entre deux tentatives de connexion
REPONSE_S = 5  # attente d'une réponse à une demande ou à une commande
CONNEXION_S = 30  # durée maximale d'une tentative de connexion
# « Connectée » : une trame d'état valide reçue depuis moins de FRAICHEUR_S,
# soit trois relevés manqués. Au-delà, la liaison est tenue pour perdue.
FRAICHEUR_S = 35
# Après une commande que la trame de réponse ne confirme pas, délai avant
# l'unique relecture de contrôle.
RELECTURE_S = 0.5

# Mesures aberrantes (protocol.FiltreDeSaut).
SAUT_MAX_TEMPERATURE_C = 10
SAUT_MAX_HUMIDITE = 30
REJETS_MAX = 3  # mesures hors plage de suite avant « inconnu »

# Vitesses : libellés des options du sélecteur, dans l'ordre du protocole.
# Conservés de ha-vmi-plus : ils sont dans l'historique.
VITESSES = ("Faible", "Moyenne", "Forte")

# Interrupteur « Vacances » : durée posée par un simple « allumer ».
# Pour une autre durée : le réglage « Vacances (jours) ».
VACANCES_JOURS_PAR_DEFAUT = 1
