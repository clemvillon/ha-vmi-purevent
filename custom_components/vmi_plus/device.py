"""Liaison Bluetooth permanente avec la VMI.

Une seule connexion (la VMI n'en accepte qu'une), tenue ouverte. Une tâche de
fond relève l'état, les sondes et la télécommande, une demande à la fois : la
réponse est attendue avant la demande suivante. Les commandes passent par le
même verrou et ne sont tenues pour faites que si la trame d'état les confirme.

« Connectée » veut dire : liaison ouverte ET trame d'état valide reçue depuis
moins de FRAICHEUR_S. Une VMI muette derrière une liaison ouverte est donc
tenue pour perdue, et la liaison est refaite.

Origine de la structure (connexion par bleak-retry-connector, verrou,
interrupteur de connexion) : ha-vmi-plus (srThibaultP, MIT) ; voir NOTICE.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
import time
from typing import Any

from bleak.exc import BleakCharacteristicNotFoundError, BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from . import protocol
from .const import (
    CARAC_COMMANDE_UUID,
    CARAC_TELEMESURE_UUID,
    CONNEXION_S,
    FERMETURE_S,
    FRAICHEUR_S,
    HORLOGE_ESSAIS_MAX,
    REJETS_MAX,
    RELECTURE_S,
    RELEVE_S,
    REPONSE_S,
    SAUT_MAX_HUMIDITE,
    SAUT_MAX_TEMPERATURE_C,
)

_LOGGER = logging.getLogger(__name__)

# Clés des mesures filtrées.
TEMPERATURE_1 = "temperature_1"
HUMIDITE_1 = "humidite_1"
TEMPERATURE_2 = "temperature_2"
TELECOMMANDE_TEMPERATURE = "telecommande_temperature"
TELECOMMANDE_HUMIDITE = "telecommande_humidite"

# Type de trame qui porte chaque mesure.
TYPE_DE_MESURE = {
    TEMPERATURE_1: protocol.TYPE_SONDES,
    HUMIDITE_1: protocol.TYPE_SONDES,
    TEMPERATURE_2: protocol.TYPE_SONDES,
    TELECOMMANDE_TEMPERATURE: protocol.TYPE_TELECOMMANDE,
    TELECOMMANDE_HUMIDITE: protocol.TYPE_TELECOMMANDE,
}

_SAUT_MAX = {
    TEMPERATURE_1: SAUT_MAX_TEMPERATURE_C,
    HUMIDITE_1: SAUT_MAX_HUMIDITE,
    TEMPERATURE_2: SAUT_MAX_TEMPERATURE_C,
    TELECOMMANDE_TEMPERATURE: SAUT_MAX_TEMPERATURE_C,
    TELECOMMANDE_HUMIDITE: SAUT_MAX_HUMIDITE,
}


class VmiHorsLigne(HomeAssistantError):
    """La VMI n'est pas joignable à cet instant."""


class VmiDevice:
    """La VMI vue de Home Assistant."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str) -> None:
        self.hass = hass
        self.address = address
        self._entry = entry
        # Interrupteur « Connexion Bluetooth » : coupé, HA libère l'unique
        # connexion (maintenance par VMI+). Toujours actif au démarrage.
        self.active = True
        self.etat: protocol.Etat | None = None
        self.mesures: dict[str, int | None] = dict.fromkeys(TYPE_DE_MESURE)
        # Dernière trame utile de chaque type reçu, en hexadécimal (diagnostic).
        self.brutes: dict[int, str] = {}
        self.trames_refusees = 0
        # Dernière trame refusée : heure, motif, contenu (diagnostic).
        self.derniere_refusee: dict[str, Any] | None = None

        self._filtres = {
            cle: protocol.FiltreDeSaut(saut, REJETS_MAX) for cle, saut in _SAUT_MAX.items()
        }
        self._recu_le: dict[int, float] = {}
        self._client: BleakClientWithServiceCache | None = None
        # Liaisons dont la fermeture n'a pas abouti (voir _fermer).
        self._a_refermer: list[BleakClientWithServiceCache] = []
        self._connecte_le = 0.0
        self._verrou = asyncio.Lock()
        self._attentes: dict[int, asyncio.Future[None]] = {}
        self._ecouteurs: list[Callable[[], None]] = []
        self._tache: asyncio.Task[None] | None = None
        self._reveil = asyncio.Event()
        self._dernier_instantane: tuple[Any, ...] | None = None
        self._perte_signalee = False
        # Échéance de fraîcheur de la dernière trame d'état (voir _sur_notification).
        self._echeance: asyncio.TimerHandle | None = None
        # Horloge de la VMI.
        self.horloge_reglee_le: datetime | None = None  # dernier accusé reçu
        self._horloge_essais = 0  # tentatives restantes pour l'occasion en cours
        self._horloge_decalage: timedelta | None = None

    # --- Lecture -----------------------------------------------------------

    @property
    def lien_ouvert(self) -> bool:
        return self._client is not None and self._client.is_connected

    def frais(self, type_trame: int) -> bool:
        """Une trame valide de ce type a été reçue depuis moins de FRAICHEUR_S."""
        recu = self._recu_le.get(type_trame)
        return recu is not None and time.monotonic() - recu < FRAICHEUR_S

    @property
    def connectee(self) -> bool:
        return self.lien_ouvert and self.frais(protocol.TYPE_ETAT)

    def mesure_disponible(self, cle: str) -> bool:
        return self.connectee and self.frais(TYPE_DE_MESURE[cle])

    @callback
    def ajouter_ecouteur(self, ecouteur: Callable[[], None]) -> Callable[[], None]:
        """Appelle `ecouteur` à chaque changement. Rend de quoi se désabonner."""
        self._ecouteurs.append(ecouteur)
        return lambda: self._ecouteurs.remove(ecouteur)

    def diagnostic(self) -> dict[str, Any]:
        maintenant = time.monotonic()
        return {
            "active": self.active,
            "lien_ouvert": self.lien_ouvert,
            "connectee": self.connectee,
            "trames_refusees": self.trames_refusees,
            "derniere_refusee": self.derniere_refusee,
            "horloge_reglee_le": (
                None if self.horloge_reglee_le is None else self.horloge_reglee_le.isoformat()
            ),
            "etat": None if self.etat is None else vars(self.etat),
            "mesures": dict(self.mesures),
            "trames": {
                f"{type_trame:02x}": {
                    "hexa": hexa,
                    # None : reçue sur une liaison précédente.
                    "age_s": (
                        round(maintenant - self._recu_le[type_trame], 1)
                        if type_trame in self._recu_le
                        else None
                    ),
                }
                for type_trame, hexa in sorted(self.brutes.items())
            },
        }

    # --- Cycle de vie ------------------------------------------------------

    @callback
    def demarrer(self) -> None:
        """Lance le relevé de fond. Ne bloque pas : si la VMI ne répond pas,
        les entités existent, indisponibles, et « Connectée » est éteinte."""
        if self._tache is None:
            self._tache = self._entry.async_create_background_task(
                self.hass, self._boucle(), f"vmi_plus relevé {self.address}"
            )

    async def arreter(self) -> None:
        if self._tache is not None:
            self._tache.cancel()
            try:
                await self._tache
            except asyncio.CancelledError:
                pass
            self._tache = None
        # Une fermeture a pu être interrompue par l'annulation de la tâche :
        # elle est reprise ici, pour rendre l'unique connexion de la VMI.
        restes, self._a_refermer = self._a_refermer, []
        await self._deconnecter()
        for client in restes:
            await self._fermer(client, dernier_essai=True)
        self._a_refermer.clear()
        if self._echeance is not None:
            self._echeance.cancel()
            self._echeance = None

    async def regler_active(self, active: bool) -> None:
        """Interrupteur « Connexion Bluetooth »."""
        self.active = active
        # L'interrupteur change d'état tout de suite, sans attendre le verrou.
        self._notifier_si_change()
        if active:
            self._reveil.set()
        elif self._client is not None:
            async with self._verrou:
                await self._deconnecter()
        # Sinon rien à fermer : une connexion en cours se refermera d'elle-même
        # (voir _assurer_connexion).
        self._notifier_si_change()

    # --- Tâche de fond -----------------------------------------------------

    async def _boucle(self) -> None:
        while True:
            try:
                if self._a_refermer:
                    # Avant toute nouvelle connexion, et même interrupteur
                    # coupé ou VMI non vue : c'est ce qui libère la VMI.
                    async with self._verrou:
                        await self._refermer_le_reste()
                if self.active:
                    await self._tour()
            except (BleakError, TimeoutError, VmiHorsLigne, OSError) as err:
                _LOGGER.debug("Relevé de la VMI %s manqué : %r", self.address, err)
            except Exception:  # la tâche de fond ne doit pas mourir
                _LOGGER.exception("Relevé de la VMI %s : erreur inattendue", self.address)
            try:
                await self._surveiller()
                self._notifier_si_change()
            except Exception:  # idem
                _LOGGER.exception("Suivi de la VMI %s : erreur inattendue", self.address)
            self._reveil.clear()
            try:
                async with asyncio.timeout(RELEVE_S):
                    await self._reveil.wait()
            except TimeoutError:
                pass

    async def _tour(self) -> None:
        """Un relevé : l'état (obligatoire), puis sondes et télécommande."""
        async with self._verrou:
            await self._assurer_connexion()
        async with self._verrou:
            await self._requete(protocol.REG_LIRE_ETAT, protocol.TYPE_ETAT)
        await self._regler_horloge_si_besoin()
        for registre, type_trame in (
            (protocol.REG_LIRE_SONDES, protocol.TYPE_SONDES),
            (protocol.REG_LIRE_TELECOMMANDE, protocol.TYPE_TELECOMMANDE),
        ):
            try:
                async with self._verrou:
                    await self._requete(registre, type_trame)
            except TimeoutError:
                _LOGGER.debug(
                    "VMI %s : pas de trame %02x à ce tour", self.address, type_trame
                )

    async def _regler_horloge_si_besoin(self) -> None:
        """Met la VMI à l'heure locale : à chaque connexion, puis quand le
        décalage horaire change (heure d'été, d'hiver). Un échec n'arrête pas
        le relevé."""
        decalage = dt_util.now().utcoffset()
        if decalage != self._horloge_decalage:
            self._horloge_decalage = decalage
            self._horloge_essais = HORLOGE_ESSAIS_MAX
        if self._horloge_essais <= 0:
            return
        self._horloge_essais -= 1
        try:
            async with self._verrou:
                maintenant = dt_util.now()  # lue au moment d'écrire
                await self._envoyer(protocol.trame_horloge(maintenant), protocol.TYPE_ACCUSE)
        except TimeoutError:
            _LOGGER.debug("VMI %s : mise à l'heure sans accusé", self.address)
            return
        self._horloge_essais = 0
        self.horloge_reglee_le = maintenant

    async def _surveiller(self) -> None:
        """Refait la liaison si la VMI est muette, et note perte et retour."""
        if (
            self.lien_ouvert
            and not self.frais(protocol.TYPE_ETAT)
            and time.monotonic() - self._connecte_le >= FRAICHEUR_S
        ):
            _LOGGER.debug("VMI %s muette : liaison refaite", self.address)
            # « Connectée » est déjà éteinte, et publiée (échéance de
            # fraîcheur) : la fermeture, qui peut durer, ne retarde rien.
            async with self._verrou:
                await self._deconnecter()
        if not self.active:
            self._perte_signalee = False
        elif self.connectee:
            if self._perte_signalee:
                _LOGGER.info("VMI %s de nouveau connectée", self.address)
            self._perte_signalee = False
        elif not self._perte_signalee:
            _LOGGER.warning(
                "VMI %s non connectée ; nouvelles tentatives en arrière-plan",
                self.address,
            )
            self._perte_signalee = True

    # --- Liaison -----------------------------------------------------------

    def _appareil(self) -> Any:
        return bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )

    async def _assurer_connexion(self) -> None:
        """Ouvre la liaison si elle ne l'est pas. Verrou tenu par l'appelant."""
        if self.lien_ouvert:
            return
        appareil = self._appareil()
        if appareil is None:
            raise VmiHorsLigne(f"VMI {self.address} non vue en Bluetooth")
        _LOGGER.debug("Connexion à la VMI %s", self.address)
        client: BleakClientWithServiceCache | None = None
        try:
            async with asyncio.timeout(CONNEXION_S):
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    appareil,
                    self.address,
                    disconnected_callback=self._sur_deconnexion,
                    max_attempts=2,
                    ble_device_callback=lambda: self._appareil() or appareil,
                )
                await client.start_notify(CARAC_TELEMESURE_UUID, self._sur_notification)
        except BleakCharacteristicNotFoundError:
            # Services mémorisés périmés (autre logiciel embarqué ?) : oubliés,
            # ils seront relus à la prochaine tentative.
            if client is not None:
                try:
                    await client.clear_cache()
                finally:
                    await self._fermer(client)
            raise
        except BaseException:
            if client is not None:
                await self._fermer(client)
            raise
        if not self.active:
            # L'interrupteur a été coupé pendant la connexion.
            await self._fermer(client)
            raise VmiHorsLigne("connexion Bluetooth coupée par l'interrupteur")
        for filtre in self._filtres.values():
            filtre.remettre_a_zero()
        # « Connectée » et les mesures attendent une trame de CETTE liaison.
        self._recu_le.clear()
        self._client = client
        self._connecte_le = time.monotonic()
        self._horloge_essais = HORLOGE_ESSAIS_MAX  # nouvelle connexion : remise à l'heure

    async def _fermer(
        self, client: BleakClientWithServiceCache, *, dernier_essai: bool = False
    ) -> None:
        """Ferme une liaison, en FERMETURE_S au plus : une liaison morte
        (relais débranché) peut ne jamais répondre.

        La VMI n'accepte qu'une connexion : une liaison mal fermée peut la
        garder prise. Si la fermeture n'aboutit pas (délai, erreur, tâche
        annulée), elle est donc reprise une fois, au tour suivant de la tâche
        de fond ou à l'arrêt ; après ce dernier essai, la liaison est
        abandonnée.
        """
        if not dernier_essai:
            self._a_refermer.append(client)
        try:
            async with asyncio.timeout(FERMETURE_S):
                await client.disconnect()
        except Exception as err:
            _LOGGER.debug(
                "VMI %s : fermeture de la liaison non aboutie%s : %r",
                self.address,
                ", abandonnée" if dernier_essai else "",
                err,
            )
            return
        if client in self._a_refermer:
            self._a_refermer.remove(client)

    async def _refermer_le_reste(self) -> None:
        """Dernier essai de fermeture des liaisons restées ouvertes. Verrou
        tenu par l'appelant. Une liaison ne sort de la liste qu'après son
        essai : si la tâche est annulée entre-temps, l'arrêt la reprend."""
        while self._a_refermer:
            client = self._a_refermer[0]
            await self._fermer(client, dernier_essai=True)
            if client in self._a_refermer:
                self._a_refermer.remove(client)

    async def _deconnecter(self) -> None:
        client, self._client = self._client, None
        self._abandonner_attentes()
        # L'état est publié avant la fermeture, qui peut durer.
        self._notifier_si_change()
        if client is not None:
            await self._fermer(client)

    def _abandonner_attentes(self) -> None:
        for attente in self._attentes.values():
            if not attente.done():
                attente.set_exception(VmiHorsLigne("liaison avec la VMI perdue"))

    def _sur_deconnexion(self, client: BleakClientWithServiceCache) -> None:
        """Appelé par la pile Bluetooth quand la liaison tombe."""
        self.hass.loop.call_soon_threadsafe(self._liaison_tombee, client)

    @callback
    def _liaison_tombee(self, client: BleakClientWithServiceCache) -> None:
        if client is not self._client:
            return
        _LOGGER.debug("VMI %s : liaison tombée, signalée par la pile Bluetooth", self.address)
        self._client = None
        self._abandonner_attentes()
        self._notifier_si_change()

    # --- Échanges ----------------------------------------------------------

    async def _requete(self, registre: int, type_attendu: int, valeur: int = 0) -> None:
        """Envoie une trame et attend une trame valide du type attendu.

        Verrou tenu par l'appelant. Lève TimeoutError sans réponse, VmiHorsLigne
        si la liaison n'est pas ouverte ou tombe pendant l'attente.
        """
        await self._envoyer(protocol.trame_commande(registre, valeur), type_attendu)

    async def _envoyer(self, trame: bytes, type_attendu: int) -> None:
        client = self._client
        if client is None or not client.is_connected:
            raise VmiHorsLigne("la VMI n'est pas connectée")
        attente: asyncio.Future[None] = self.hass.loop.create_future()
        self._attentes[type_attendu] = attente
        try:
            async with asyncio.timeout(REPONSE_S):
                await client.write_gatt_char(CARAC_COMMANDE_UUID, trame, response=True)
                await attente
        finally:
            self._attentes.pop(type_attendu, None)
            if attente.done() and not attente.cancelled():
                attente.exception()  # lue ici pour ne pas la laisser orpheline

    def _sur_notification(self, _carac: Any, donnees: bytearray) -> None:
        """Une trame arrive de la VMI."""
        if self._client is None:
            # Réponse tardive d'une liaison déjà abandonnée (en cours de
            # fermeture) : elle ne dit rien de la liaison courante.
            return
        trame = bytes(donnees)
        defaut = protocol.defaut_de_trame(trame)
        if defaut is not None:
            self._refuser(trame, defaut)
            return
        type_trame = trame[protocol.POS_TYPE]
        if type_trame == protocol.TYPE_ETAT:
            etat = protocol.decoder_etat(trame)
            if etat is None:
                self._refuser(trame, protocol.REFUS_TROP_COURTE)
                return
            self.etat = etat
        elif type_trame == protocol.TYPE_SONDES:
            sondes = protocol.decoder_sondes(trame)
            if sondes is None:
                self._refuser(trame, protocol.REFUS_TROP_COURTE)
                return
            self._filtrer(TEMPERATURE_1, sondes.temperature_1_c)
            self._filtrer(HUMIDITE_1, sondes.humidite_1)
            self._filtrer(TEMPERATURE_2, sondes.temperature_2_c)
        elif type_trame == protocol.TYPE_TELECOMMANDE:
            telecommande = protocol.decoder_telecommande(trame)
            if telecommande is None:
                self._refuser(trame, protocol.REFUS_TROP_COURTE)
                return
            self._filtrer(TELECOMMANDE_TEMPERATURE, telecommande.temperature_c)
            self._filtrer(TELECOMMANDE_HUMIDITE, telecommande.humidite)
        self.brutes[type_trame] = protocol.trame_utile(trame).hex()
        self._recu_le[type_trame] = time.monotonic()
        if type_trame == protocol.TYPE_ETAT:
            self._armer_echeance(FRAICHEUR_S)
        attente = self._attentes.get(type_trame)
        if attente is not None and not attente.done():
            attente.set_result(None)
        self._notifier_si_change()

    def _refuser(self, trame: bytes, motif: str) -> None:
        """Compte une trame refusée, la garde pour le diagnostic et la note au
        journal détaillé. Elle ne change aucun état."""
        self.trames_refusees += 1
        utile = trame.rstrip(b"\x00")
        self.derniere_refusee = {
            "le": dt_util.now().isoformat(timespec="seconds"),
            "motif": motif,
            "octets": len(trame),
            # Sans les zéros de fin.
            "hexa": utile.hex(),
        }
        _LOGGER.debug(
            "VMI %s : trame refusée (%s), %d octets : %s",
            self.address,
            motif,
            len(trame),
            utile.hex(),
        )

    def _armer_echeance(self, dans_s: float) -> None:
        """« Connectée » s'éteint FRAICHEUR_S après la dernière trame d'état :
        l'échéance le publie à ce moment-là, quoi que fasse la tâche de fond
        (une écriture ou une fermeture en attente sur une liaison morte)."""
        if self._echeance is not None:
            self._echeance.cancel()
        self._echeance = self.hass.loop.call_later(dans_s, self._echeance_atteinte)

    @callback
    def _echeance_atteinte(self) -> None:
        self._echeance = None
        recu = self._recu_le.get(protocol.TYPE_ETAT)
        if recu is not None:
            reste = FRAICHEUR_S - (time.monotonic() - recu)
            if reste > 0:  # réveil un rien trop tôt : on attend le reste
                self._armer_echeance(reste)
                return
        if self.lien_ouvert:
            _LOGGER.debug(
                "VMI %s : plus de trame d'état depuis %s s, liaison encore ouverte",
                self.address,
                FRAICHEUR_S,
            )
        self._notifier_si_change()

    def _filtrer(self, cle: str, mesure: int | None) -> None:
        self.mesures[cle] = self._filtres[cle].filtrer(mesure)

    # --- Commandes ---------------------------------------------------------

    def _exiger_la_liaison(self) -> None:
        """Hors liaison, une commande échoue tout de suite : elle n'attend pas
        derrière une tentative de connexion."""
        if not self.lien_ouvert:
            raise VmiHorsLigne("la VMI n'est pas connectée")

    async def commander(
        self,
        libelle: str,
        registre: int,
        valeur: int,
        confirme: Callable[[protocol.Etat], bool],
        *,
        sauf_si_deja: bool = False,
    ) -> None:
        """Écrit un registre ; réussit seulement si la trame d'état confirme.

        `sauf_si_deja` : l'état est d'abord relu, et rien n'est envoyé s'il est
        déjà celui voulu. Pour une bascule (une commande de trop l'inverserait)
        et pour « allumer » (ne pas ramener des vacances en cours à 1 jour).
        Une extinction, elle, est toujours envoyée : l'état gardé en mémoire
        peut dater du relevé précédent.
        """
        self._exiger_la_liaison()
        async with self._verrou:
            if sauf_si_deja:
                try:
                    await self._requete(protocol.REG_LIRE_ETAT, protocol.TYPE_ETAT)
                except VmiHorsLigne:
                    raise
                except (BleakError, TimeoutError, OSError) as err:
                    raise HomeAssistantError(f"{libelle} : la VMI n'a pas répondu") from err
                if self.etat is not None and confirme(self.etat):
                    return
            await self._commander(libelle, registre, valeur, confirme)

    async def _commander(
        self,
        libelle: str,
        registre: int,
        valeur: int,
        confirme: Callable[[protocol.Etat], bool],
    ) -> None:
        """Verrou tenu par l'appelant. La commande n'est envoyée qu'une fois :
        si la réponse manque ou ne confirme pas, l'état est relu, jamais la
        commande renvoyée (une bascule renvoyée s'annulerait)."""
        try:
            try:
                await self._requete(registre, protocol.TYPE_ETAT, valeur)
            except TimeoutError:
                # Écrite, mais sans trame en retour : la relecture tranchera.
                _LOGGER.debug("VMI %s : %s sans réponse, relecture", self.address, libelle)
            else:
                if self.etat is not None and confirme(self.etat):
                    return
                await asyncio.sleep(RELECTURE_S)
            await self._requete(protocol.REG_LIRE_ETAT, protocol.TYPE_ETAT)
        except VmiHorsLigne:
            raise
        except (BleakError, TimeoutError, OSError) as err:
            raise HomeAssistantError(f"{libelle} : la VMI n'a pas répondu") from err
        if self.etat is None or not confirme(self.etat):
            raise HomeAssistantError(f"{libelle} : la VMI n'a pas confirmé la commande")

    async def arreter_prechauffage(self) -> None:
        """Arrêt complet du préchauffage : marche à 0 et consigne à 0.

        Les deux commandes ne peuvent que baisser la puissance. La seconde
        (consigne à 0, qui arrête aussi) part si la première n'a pas suffi :
        non confirmée, ou consigne restée posée (cas d'une consigne laissée par
        les plages horaires, préchauffage à l'arrêt).
        """
        libelle = "Arrêt du préchauffage"

        def arrete(etat: protocol.Etat) -> bool:
            return not etat.prechauffage_marche and etat.prechauffage_consigne_c == 0

        self._exiger_la_liaison()
        async with self._verrou:
            confirmee = True
            try:
                await self._commander(
                    libelle,
                    protocol.REG_PRECHAUFFAGE_MARCHE,
                    0,
                    lambda etat: not etat.prechauffage_marche,
                )
            except VmiHorsLigne:
                raise
            except HomeAssistantError as err:
                # L'état en mémoire date d'avant la commande : il ne prouve rien.
                confirmee = False
                _LOGGER.debug("VMI %s : %s ; essai par la consigne", self.address, err)
            if not confirmee or self.etat is None or not arrete(self.etat):
                await self._commander(
                    libelle, protocol.REG_PRECHAUFFAGE_CONSIGNE, 0, arrete
                )

    # --- Écouteurs ---------------------------------------------------------

    def _instantane(self) -> tuple[Any, ...]:
        return (
            self.active,
            self.connectee,
            self.etat,
            tuple(self.mesures.values()),
            self.frais(protocol.TYPE_SONDES),
            self.frais(protocol.TYPE_TELECOMMANDE),
        )

    @callback
    def _notifier_si_change(self) -> None:
        instantane = self._instantane()
        if instantane == self._dernier_instantane:
            return
        self._dernier_instantane = instantane
        for ecouteur in list(self._ecouteurs):
            try:
                ecouteur()
            except Exception:  # un écouteur en défaut ne prive pas les autres
                _LOGGER.exception("VMI %s : écouteur en défaut", self.address)
