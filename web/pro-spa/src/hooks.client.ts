// 30.7.2026 cache-parannus: tämä tiedosto on olemassa jotta SvelteKitin
// app-entryn sisältö (ja siten sen hash-tiedostonimi) muuttui — edellisen
// entry-URL:n (app.Cbaia9eI.js) edge-cache-merkintä myrkyttyi deploy-ikkunassa
// (fallback-HTML immutable-headerilla → selain/edge ei koskaan revalidoi).
// Uusi nimi ohittaa myrkytetyn merkinnän kaikilta käyttäjiltä ilman purgea.
// Tiedosto saa jäädä: client-hookit ovat muutenkin laillinen laajennuspiste.
export {};
