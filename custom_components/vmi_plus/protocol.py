"""Protocole Bluetooth de la VMI Ventilairsec Purevent (VisionAir).

Module pur : ni Home Assistant, ni Bluetooth. Il construit les trames à
envoyer et décode celles que la VMI renvoie.

Origine : adapté de visionair-ble (Bart Cortooms, MIT, commit 6661e2a) et de
ha-vmi-plus (srThibaultP, MIT, commit 1283a8f) ; voir NOTICE. Les registres et
les positions d'octets ont été vérifiés sur une Purevent (logiciel 6.4.002)
par une capture du 04/10/2026 (non publiée). Là où cette capture contredit
les bibliothèques d'origine, c'est elle qui fait foi : consigne de préchauffage
en octet 35, débit sur deux octets, débit fixe 0x1b, surventilation 0x0b.

Hors capture : le Boost (registre 0x19, octet 44), que les deux bibliothèques
donnent pareil et qui a été essayé sur la même Purevent par ha-vmi-plus le
03/10/2026. Sondes et télécommande : une seule trame de chaque dans la
capture, valeurs égales à celles affichées par VMI+.

Forme d'une trame, dans les deux sens :

    A5 B6 | type | 06 | longueur n | n octets | somme

La somme est le XOR de tous les octets depuis le type jusqu'au dernier octet
utile. Les notifications font 182 octets : au-delà de la somme, des zéros.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

# --- Trame -----------------------------------------------------------------

ENTETE = b"\xa5\xb6"
POS_TYPE = 2
POS_LONGUEUR = 4
POS_DONNEES = 5

# Types envoyés à la VMI
TYPE_COMMANDE = 0x10
TYPE_HORLOGE = 0x1A

# Types reçus de la VMI
TYPE_ETAT = 0x01
TYPE_TELECOMMANDE = 0x02
TYPE_SONDES = 0x03
TYPE_ACCUSE = 0x23

# --- Registres (octet 5 d'une trame de commande) ---------------------------

# Lectures : la VMI répond par une notification, sans rien changer.
REG_LIRE_ETAT = 0x03  # -> TYPE_ETAT
REG_LIRE_TELECOMMANDE = 0x06  # -> TYPE_TELECOMMANDE
REG_LIRE_SONDES = 0x07  # -> TYPE_SONDES

# Commandes : la VMI répond par une trame d'état à jour.
REG_SURVENTILATION = 0x0B  # bascule : chaque envoi inverse l'état
REG_LIMITE_ETE = 0x17  # °C
REG_VITESSE = 0x18  # 0, 1, 2
REG_BOOST = 0x19  # 1 / 0
REG_VACANCES = 0x1A  # nombre de jours, 0 = arrêt
REG_DEBIT_FIXE = 0x1B  # 1 / 0
# Préchauffage : les deux registres sont liés (capture du 04/10/2026).
# Régler une consigne (12 à 18) met aussi le préchauffage en marche ;
# la consigne 0 l'arrête ; l'arrêt par 0x2f remet la consigne à 0.
REG_PRECHAUFFAGE_CONSIGNE = 0x1C  # °C, 0 = pas de préchauffage
REG_PRECHAUFFAGE_MARCHE = 0x2F  # 1 / 0

# --- Trame d'état (TYPE_ETAT) ----------------------------------------------

ETAT_LONGUEUR = 61  # octets utiles, somme comprise
ETAT_VOLUME = 22  # 2 octets, poids faible d'abord, m³
ETAT_JOURS_FONCTIONNEMENT = 26  # 2 octets
ETAT_JOURS_FILTRE = 28  # 2 octets
ETAT_SURVENTILATION = 33  # logique inversée : 0 = active
ETAT_VITESSE = 34
ETAT_PRECHAUFFAGE_CONSIGNE = 35
ETAT_OCTET_36 = 36  # non décodé, surveillé
ETAT_LIMITE_ETE = 38
ETAT_VACANCES = 43  # jours restants
ETAT_BOOST = 44
ETAT_DEBIT_FIXE = 45
ETAT_RENOUVELLEMENT = 47  # 2 octets : volumes par heure x 1000
ETAT_SURVENTILATION_BIS = 52  # 1 = active (double de l'octet 33)
ETAT_PRECHAUFFAGE_MARCHE = 53

SURVENTILATION_ACTIVE = 0x00
VITESSE_MAX = 2
RENOUVELLEMENT_DIVISEUR = 1000

# --- Trame des sondes (TYPE_SONDES) et de la télécommande ------------------

SONDES_LONGUEUR = 12
SONDES_TEMPERATURE_1 = 6  # sonde n°1, sortie des résistances
SONDES_HUMIDITE_1 = 8
SONDES_TEMPERATURE_2 = 11  # sonde n°2, entrée d'air

TELECOMMANDE_LONGUEUR = 14
TELECOMMANDE_TEMPERATURE = 11
TELECOMMANDE_HUMIDITE = 13

# --- Bornes ----------------------------------------------------------------

# Hors de ces plages, une mesure est tenue pour fausse.
TEMPERATURE_MIN_C = -30
TEMPERATURE_MAX_C = 70
HUMIDITE_MIN = 0
HUMIDITE_MAX = 100

# Réglages : les listes de l'app VMI+.
PRECHAUFFAGE_CONSIGNE_MIN_C = 12
PRECHAUFFAGE_CONSIGNE_MAX_C = 18
LIMITE_ETE_MIN_C = 22
LIMITE_ETE_MAX_C = 37
VACANCES_MAX_JOURS = 255  # un octet


def somme(donnees: bytes) -> int:
    """XOR de tous les octets."""
    resultat = 0
    for octet in donnees:
        resultat ^= octet
    return resultat


def _fermer(corps: bytes) -> bytes:
    """Ajoute l'en-tête devant et la somme derrière."""
    return ENTETE + corps + bytes([somme(corps)])


def trame_commande(registre: int, valeur: int = 0) -> bytes:
    """Trame de 11 octets : lecture (valeur 0) ou commande d'un registre."""
    if not 0 <= registre <= 0xFF or not 0 <= valeur <= 0xFF:
        raise ValueError("registre et valeur tiennent sur un octet")
    return _fermer(bytes([TYPE_COMMANDE, 0x06, 0x05, registre, 0, 0, 0, valeur]))


def trame_horloge(maintenant: datetime) -> bytes:
    """Mise à l'heure : année sur deux chiffres, mois, jour, heure, minute,
    seconde, en heure locale (comme VMI+ à chaque connexion)."""
    return _fermer(
        bytes(
            [
                TYPE_HORLOGE,
                0x06,
                0x06,
                maintenant.year % 100,
                maintenant.month,
                maintenant.day,
                maintenant.hour,
                maintenant.minute,
                maintenant.second,
            ]
        )
    )


def type_de_trame(donnees: bytes) -> int | None:
    """Type d'une trame reçue, ou None si elle n'est pas valide.

    Valide : en-tête, longueur annoncée présente, somme juste.
    """
    if len(donnees) <= POS_DONNEES or donnees[:2] != ENTETE:
        return None
    fin = POS_DONNEES + donnees[POS_LONGUEUR]
    if len(donnees) <= fin:
        return None
    if somme(donnees[POS_TYPE:fin]) != donnees[fin]:
        return None
    return donnees[POS_TYPE]


def trame_utile(donnees: bytes) -> bytes:
    """La trame sans les zéros de remplissage. À n'appeler que sur une trame
    valide."""
    return bytes(donnees[: POS_DONNEES + donnees[POS_LONGUEUR] + 1])


def _mot(donnees: bytes, position: int) -> int:
    return int.from_bytes(donnees[position : position + 2], "little")


def _signe(octet: int) -> int:
    """Octet lu comme entier signé. Hypothèse pour les températures sous
    0 °C : jamais observée à ce jour, à vérifier contre VMI+."""
    return octet - 256 if octet >= 0x80 else octet


def _temperature(octet: int) -> int | None:
    valeur = _signe(octet)
    if TEMPERATURE_MIN_C <= valeur <= TEMPERATURE_MAX_C:
        return valeur
    return None


def _humidite(octet: int) -> int | None:
    if HUMIDITE_MIN <= octet <= HUMIDITE_MAX:
        return octet
    return None


@dataclass(frozen=True)
class Etat:
    """Ce que dit une trame d'état."""

    volume_m3: int
    jours_fonctionnement: int
    jours_filtre: int
    surventilation: bool
    vitesse: int | None  # 0, 1, 2 ; None si la valeur est inconnue
    prechauffage_consigne_c: int  # 0 = pas de préchauffage
    octet_36: int
    limite_ete_c: int
    vacances_jours: int
    boost: bool
    debit_fixe: bool
    renouvellement: int  # volumes par heure x 1000
    prechauffage_marche: bool
    brute: str  # la trame utile, en hexadécimal

    @property
    def debit_m3h(self) -> int:
        """Débit théorique, comme l'affiche VMI+."""
        return round(self.renouvellement * self.volume_m3 / RENOUVELLEMENT_DIVISEUR)


@dataclass(frozen=True)
class Sondes:
    """Sondes du caisson. None : valeur hors plage."""

    temperature_1_c: int | None
    humidite_1: int | None
    temperature_2_c: int | None


@dataclass(frozen=True)
class Telecommande:
    """Sonde de la télécommande. None : valeur hors plage."""

    temperature_c: int | None
    humidite: int | None


def decoder_etat(donnees: bytes) -> Etat | None:
    """Décode une trame d'état valide ; None si ce n'en est pas une."""
    if type_de_trame(donnees) != TYPE_ETAT:
        return None
    utile = trame_utile(donnees)
    if len(utile) < ETAT_LONGUEUR:
        return None
    vitesse = utile[ETAT_VITESSE]
    return Etat(
        volume_m3=_mot(utile, ETAT_VOLUME),
        jours_fonctionnement=_mot(utile, ETAT_JOURS_FONCTIONNEMENT),
        jours_filtre=_mot(utile, ETAT_JOURS_FILTRE),
        surventilation=utile[ETAT_SURVENTILATION] == SURVENTILATION_ACTIVE,
        vitesse=vitesse if vitesse <= VITESSE_MAX else None,
        prechauffage_consigne_c=utile[ETAT_PRECHAUFFAGE_CONSIGNE],
        octet_36=utile[ETAT_OCTET_36],
        limite_ete_c=utile[ETAT_LIMITE_ETE],
        vacances_jours=utile[ETAT_VACANCES],
        boost=utile[ETAT_BOOST] == 0x01,
        debit_fixe=utile[ETAT_DEBIT_FIXE] == 0x01,
        renouvellement=_mot(utile, ETAT_RENOUVELLEMENT),
        prechauffage_marche=utile[ETAT_PRECHAUFFAGE_MARCHE] == 0x01,
        brute=utile.hex(),
    )


def decoder_sondes(donnees: bytes) -> Sondes | None:
    """Décode une trame des sondes valide ; None si ce n'en est pas une."""
    if type_de_trame(donnees) != TYPE_SONDES:
        return None
    utile = trame_utile(donnees)
    if len(utile) < SONDES_LONGUEUR:
        return None
    return Sondes(
        temperature_1_c=_temperature(utile[SONDES_TEMPERATURE_1]),
        humidite_1=_humidite(utile[SONDES_HUMIDITE_1]),
        temperature_2_c=_temperature(utile[SONDES_TEMPERATURE_2]),
    )


def decoder_telecommande(donnees: bytes) -> Telecommande | None:
    """Décode une trame de la télécommande valide ; None sinon."""
    if type_de_trame(donnees) != TYPE_TELECOMMANDE:
        return None
    utile = trame_utile(donnees)
    if len(utile) < TELECOMMANDE_LONGUEUR:
        return None
    return Telecommande(
        temperature_c=_temperature(utile[TELECOMMANDE_TEMPERATURE]),
        humidite=_humidite(utile[TELECOMMANDE_HUMIDITE]),
    )


class FiltreDeSaut:
    """Écarte une mesure isolée qui s'éloigne trop de la précédente.

    Un saut de plus de `saut_max` n'est retenu que si le relevé suivant le
    confirme. Cas réel : la sonde n°1 lue à 0 °C pendant un relevé le
    04/10/2026, entre deux relevés à 25 °C.

    Sans valeur connue (démarrage, reconnexion), la première mesure attend
    elle aussi d'être confirmée par la suivante : la valeur reste inconnue un
    relevé de plus, mais une mesure fausse ne passe pas.

    Une mesure hors plage (None) garde la valeur précédente ; au bout de
    `rejets_max` mesures hors plage de suite, la valeur devient inconnue.
    """

    def __init__(self, saut_max: float, rejets_max: int) -> None:
        self._saut_max = saut_max
        self._rejets_max = rejets_max
        self.valeur: int | None = None
        self._candidat: int | None = None
        self._rejets = 0

    def remettre_a_zero(self) -> None:
        """Après une coupure : on repart sans valeur connue."""
        self.valeur = None
        self._candidat = None
        self._rejets = 0

    def filtrer(self, mesure: int | None) -> int | None:
        """Rend la valeur à afficher après cette mesure."""
        if mesure is None:
            self._rejets += 1
            if self._rejets >= self._rejets_max:
                self.valeur = None
                self._candidat = None
            return self.valeur
        self._rejets = 0
        proche_de_la_valeur = (
            self.valeur is not None and abs(mesure - self.valeur) <= self._saut_max
        )
        confirme_le_candidat = (
            self._candidat is not None
            and abs(mesure - self._candidat) <= self._saut_max
        )
        if proche_de_la_valeur or confirme_le_candidat:
            self.valeur = mesure
            self._candidat = None
        else:
            self._candidat = mesure
        return self.valeur
