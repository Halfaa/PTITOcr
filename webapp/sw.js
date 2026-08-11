// Service worker minimal.
//
// Il met en cache la coquille de l'application -- page, manifeste, icones --
// pour qu'elle s'ouvre sans reseau et soit installable depuis le navigateur
// du telephone.
//
// Il ne met JAMAIS en cache /api/. L'extraction depend d'un modele de
// plusieurs gigaoctets qui vit sur le serveur : servir une reponse d'API
// depuis le cache afficherait les resultats de la facture precedente sur la
// photo courante, ce qui est bien pire que d'afficher une erreur reseau.

const CACHE = "factures-v1";
const COQUILLE = ["/", "/manifest.json"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(COQUILLE)));
  self.skipWaiting();
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys().then(cles =>
    Promise.all(cles.filter(c => c !== CACHE).map(c => caches.delete(c)))));
  self.clients.claim();
});

self.addEventListener("fetch", e => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/") || e.request.method !== "GET") return;

  // Reseau d'abord : la page evolue a chaque deploiement, et une coquille
  // perimee servie depuis le cache est un faux probleme tres desagreable a
  // diagnostiquer. Le cache n'intervient que hors ligne.
  e.respondWith(
    fetch(e.request)
      .then(r => {
        const copie = r.clone();
        caches.open(CACHE).then(c => c.put(e.request, copie));
        return r;
      })
      .catch(() => caches.match(e.request))
  );
});
