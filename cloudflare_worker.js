// GridTracker - Cloudflare Worker
// Deploy: https://workers.cloudflare.com (ücretsiz, 100k istek/gün)
// URL örnek: https://gridtracker-price.KULLANICI.workers.dev/EREGL
// HTML'de WORKER_URL sabiti olarak tanımla

export default {
  async fetch(request) {
    const sym = new URL(request.url).pathname.replace('/', '').toUpperCase().trim();
    if (!sym) return new Response('sym gerekli', { status: 400 });

    const url = `https://query2.finance.yahoo.com/v8/finance/chart/${sym}.IS?interval=1d&range=5d`;
    const r = await fetch(url, {
      headers: { 'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json' }
    });
    const d = await r.json();
    const result = d?.chart?.result?.[0];
    if (!result) return new Response(JSON.stringify({ error: 'veri yok' }), { status: 502, headers: cors() });

    const price = result.meta?.regularMarketPrice
      ?? result.indicators.quote[0].close.filter(Boolean).at(-1);

    return new Response(
      JSON.stringify({ price: Math.round(price * 100) / 100 }),
      { headers: cors() }
    );
  }
};

function cors() {
  return {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
  };
}
