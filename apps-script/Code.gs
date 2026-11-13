/**
 * Capitu Food - servidor do painel em Google Apps Script.
 *
 * Recebe os cliques da página (GitHub Pages), fala com a Tuya e guarda as fotos no Drive.
 * Nenhum segredo fica neste arquivo: tudo vem das Propriedades do script
 * (Configurações do projeto > Propriedades do script):
 *
 *   TUYA_ACCESS_ID       Access ID do projeto na Tuya
 *   TUYA_ACCESS_SECRET   Access Secret do projeto na Tuya
 *   TUYA_DEVICE_ID       ID do comedouro
 *   TUYA_ENDPOINT        opcional, padrão https://openapi.tuyaus.com
 *   SENHA_PAINEL         senha que a página pede para entrar
 *   TOKEN_ROBO           senha longa usada só pelo GitHub Actions para mandar fotos
 *   PASTA_FOTOS_ID       opcional; se faltar, a pasta é criada no Drive na primeira foto
 *   GITHUB_TOKEN         token do GitHub (só "Actions: Read and write" neste repositório) que permite
 *                        ao Google chamar o robô de fotos na hora certa
 *   GITHUB_REPO          opcional, padrão lffzdsf/capitufood
 */

var PROPS = PropertiesService.getScriptProperties();
var NOME_PASTA = 'Capitu - fotos do comedouro';
var MAX_INDICE = 24;        // quantas fotos recentes o painel conhece
var SESSAO_DIAS = 30;
var MAX_FALHAS = 5;         // tentativas de senha antes do bloqueio
var BLOQUEIO_SEG = 900;

// Data points que a página pode gravar, com validação de valor.
var GRAVAVEIS = {
  manual_feed: function (v) { return inteiro_(v) && v >= 1 && v <= 10; },
  dev_volume_adjust: function (v) { return inteiro_(v) && v >= 0 && v <= 100; },
  basic_private: function (v) { return typeof v === 'boolean'; },
  basic_osd: function (v) { return typeof v === 'boolean'; },
  motion_switch: function (v) { return typeof v === 'boolean'; },
  motion_sensitivity: function (v) { return v === '0' || v === '1' || v === '2'; },
  basic_nightvision: function (v) { return v === '0' || v === '1' || v === '2'; }
};

/* ============================ entrada ============================ */

function doGet() {
  return json_({ ok: true, servico: 'capitu-food' });
}

function doPost(e) {
  var corpo;
  try {
    corpo = JSON.parse(e.postData.contents);
  } catch (err) {
    return json_({ ok: false, erro: 'corpo inválido' });
  }
  try {
    return json_(rotear_(corpo || {}));
  } catch (err) {
    return json_({ ok: false, erro: String(err && err.message || err), codigo: err && err.codigo || 'erro' });
  }
}

function rotear_(c) {
  var acao = String(c.acao || '');
  if (acao === 'login') return { ok: true, sessao: login_(c.senha) };

  // O robô (GitHub Actions) só pode pedir e entregar fotos.
  if (acao === 'fotoPendente' || acao === 'fotoSalvar') {
    exigirRobo_(c.robo);
    return acao === 'fotoPendente' ? fotoPendente_() : fotoSalvar_(c);
  }

  exigirSessao_(c.sessao);
  switch (acao) {
    case 'estado': return estado_();
    case 'historico': return { ok: true, itens: historico_() };
    case 'definir': return definir_(c.code, c.value);
    case 'agenda': return gravarAgenda_(c.itens);
    case 'video': return { ok: true, url: tuya_('POST', '/v1.0/devices/' + dispositivo_() + '/stream/actions/allocate', { type: 'hls' }).url };
    case 'fotos': return fotos_();
    case 'fotoVer': return fotoVer_(c.id);
    case 'fotosConfig': return fotosConfig_(c);
    default: throw erro_('ação desconhecida: ' + acao);
  }
}

/* ============================ acesso ============================ */

function login_(senha) {
  var cache = CacheService.getScriptCache();
  var falhas = Number(cache.get('falhas') || 0);
  if (falhas >= MAX_FALHAS) throw erro_('Muitas tentativas. Aguarde 15 minutos.', 'bloqueado');
  var certa = prop_('SENHA_PAINEL');
  if (!certa) throw erro_('Defina SENHA_PAINEL nas propriedades do script.', 'config');
  if (typeof senha !== 'string' || !igual_(senha, certa)) {
    cache.put('falhas', String(falhas + 1), BLOQUEIO_SEG);
    throw erro_('Senha incorreta.', 'login');
  }
  cache.remove('falhas');
  var validade = Date.now() + SESSAO_DIAS * 86400000;
  return validade + '.' + assinarSessao_(validade);
}

function assinarSessao_(validade) {
  var chave = prop_('CHAVE_SESSAO');
  if (!chave) { chave = Utilities.getUuid() + Utilities.getUuid(); PROPS.setProperty('CHAVE_SESSAO', chave); }
  // Trocar a senha invalida todas as sessões antigas.
  return hmacHex_(String(validade), chave + '|' + prop_('SENHA_PAINEL'));
}

function exigirSessao_(sessao) {
  var partes = String(sessao || '').split('.');
  var validade = Number(partes[0]);
  if (partes.length !== 2 || !validade || validade < Date.now() || !igual_(partes[1], assinarSessao_(validade))) {
    throw erro_('Entre com a senha do painel.', 'login');
  }
}

function exigirRobo_(token) {
  var certo = prop_('TOKEN_ROBO');
  if (!certo || typeof token !== 'string' || !igual_(token, certo)) throw erro_('robô não autorizado', 'login');
}

/* ============================ Tuya ============================ */

function dispositivo_() {
  var id = prop_('TUYA_DEVICE_ID');
  if (!id) throw erro_('Defina TUYA_DEVICE_ID nas propriedades do script.', 'config');
  return id;
}

function tuya_(metodo, caminho, corpo, semToken) {
  var id = prop_('TUYA_ACCESS_ID'), segredo = prop_('TUYA_ACCESS_SECRET');
  if (!id || !segredo) throw erro_('Defina TUYA_ACCESS_ID e TUYA_ACCESS_SECRET nas propriedades do script.', 'config');
  var base = (prop_('TUYA_ENDPOINT') || 'https://openapi.tuyaus.com').replace(/\/+$/, '');

  // A URL assinada precisa ter os parâmetros em ordem alfabética.
  var q = caminho.indexOf('?');
  if (q >= 0) caminho = caminho.slice(0, q) + '?' + caminho.slice(q + 1).split('&').sort().join('&');

  var dados = corpo === undefined || corpo === null ? '' : JSON.stringify(corpo);
  var t = String(Date.now()), nonce = Utilities.getUuid().replace(/-/g, '');
  var token = semToken ? '' : tokenTuya_();
  var aAssinar = [metodo, sha256Hex_(dados), '', caminho].join('\n');
  var cab = {
    client_id: id,
    sign: hmacHex_(id + token + t + nonce + aAssinar, segredo).toUpperCase(),
    t: t,
    nonce: nonce,
    sign_method: 'HMAC-SHA256'
  };
  if (token) cab.access_token = token;
  var opcoes = { method: metodo.toLowerCase(), headers: cab, contentType: 'application/json', muteHttpExceptions: true };
  if (dados) opcoes.payload = dados;

  var resp = UrlFetchApp.fetch(base + caminho, opcoes), r;
  try { r = JSON.parse(resp.getContentText()); } catch (err) { throw erro_('Tuya respondeu HTTP ' + resp.getResponseCode()); }
  if (!r.success) {
    if (r.code === 1010 || r.code === 1011) CacheService.getScriptCache().remove('tuya_token');
    throw erro_('Tuya recusou: código ' + r.code + ' - ' + r.msg, 'tuya');
  }
  return r.result;
}

function tokenTuya_() {
  var cache = CacheService.getScriptCache();
  var token = cache.get('tuya_token');
  if (token) return token;
  var r = tuya_('GET', '/v1.0/token?grant_type=1', null, true);
  cache.put('tuya_token', r.access_token, Math.max(60, Math.min(21600, Number(r.expire_time) - 120)));
  return r.access_token;
}

function propriedades_() {
  var lista = tuya_('GET', '/v2.0/cloud/thing/' + dispositivo_() + '/shadow/properties').properties || [];
  var mapa = {};
  lista.forEach(function (p) { mapa[p.code] = p.value; });
  return mapa;
}

function emitir_(code, valor) {
  var props = {};
  props[code] = valor;
  return tuya_('POST', '/v2.0/cloud/thing/' + dispositivo_() + '/shadow/properties/issue', { properties: JSON.stringify(props) });
}

/* ============================ painel ============================ */

function estado_() {
  var info = tuya_('GET', '/v1.0/devices/' + dispositivo_());
  var props = propriedades_();
  var ultima = null;
  try { ultima = JSON.parse(props.feed_record || 'null'); } catch (err) { /* sem registro */ }
  var visiveis = {};
  Object.keys(GRAVAVEIS).concat(['feed_state', 'battery_value', 'weight_part']).forEach(function (k) {
    visiveis[k] = props[k] === undefined ? null : props[k];
  });
  return {
    ok: true,
    nome: info.name,
    modelo: info.product_name,
    online: info.online,
    props: visiveis,
    ultima_refeicao: ultima,
    agenda: decodificarAgenda_(props.meal_plan2 || '')
  };
}

function historico_() {
  var fim = Date.now(), ini = fim - 7 * 86400000;
  var r = tuya_('GET', '/v2.1/cloud/thing/' + dispositivo_() + '/report-logs?codes=feed_record&start_time=' + ini + '&end_time=' + fim + '&size=50');
  var itens = [];
  (r.logs || []).forEach(function (l) {
    try {
      var v = JSON.parse(l.value);
      if (v && v.time) itens.push({ hora: v.time, porcoes: v.value, manual: v.type === 1 });
    } catch (err) { /* ignora registro malformado */ }
  });
  return itens;
}

function definir_(code, valor) {
  if (!Object.prototype.hasOwnProperty.call(GRAVAVEIS, code) || !GRAVAVEIS[code](valor)) throw erro_('valor não permitido para ' + code);
  emitir_(code, valor);
  return { ok: true };
}

/* meal_plan2: blocos de 4 bytes em hexadecimal:
   dias (bitmask) | hora | minuto | porções (nibble alto) + ligado (nibble baixo). */
function decodificarAgenda_(hexa) {
  var itens = [];
  for (var i = 0; i + 8 <= hexa.length; i += 8) {
    var dias = parseInt(hexa.substr(i, 2), 16), porcoes = parseInt(hexa.substr(i + 6, 1), 16);
    if (isNaN(dias) || isNaN(porcoes)) return [];
    itens.push({ dias: dias, hora: hexa.substr(i + 2, 2) + ':' + hexa.substr(i + 4, 2), porcoes: porcoes, ligado: hexa.substr(i + 7, 1) !== '0' });
  }
  return itens;
}

function codificarAgenda_(itens) {
  if (!Array.isArray(itens) || itens.length > 10) throw erro_('a agenda aceita no máximo 10 horários');
  var vistos = {}, blocos = [];
  itens.forEach(function (it) {
    var m = it && typeof it.hora === 'string' ? /^(\d\d):(\d\d)$/.exec(it.hora) : null;
    if (!m || Number(m[1]) > 23 || Number(m[2]) > 59) throw erro_('hora inválida: ' + (it && it.hora));
    if (!inteiro_(it.dias) || it.dias < 1 || it.dias > 127) throw erro_('dias inválidos');
    if (!inteiro_(it.porcoes) || it.porcoes < 1 || it.porcoes > 9) throw erro_('porções devem ser de 1 a 9');
    if (typeof it.ligado !== 'boolean') throw erro_('campo ligado inválido');
    var chave = m[1] + m[2];
    if (vistos[chave]) throw erro_('há dois horários iguais');
    vistos[chave] = true;
    blocos.push({ chave: chave, hex: ('0' + it.dias.toString(16)).slice(-2) + chave + it.porcoes.toString(16) + (it.ligado ? '1' : '0') });
  });
  blocos.sort(function (a, b) { return a.chave < b.chave ? -1 : a.chave > b.chave ? 1 : 0; });
  return blocos.map(function (b) { return b.hex; }).join('');
}

function gravarAgenda_(itens) {
  var hexa = codificarAgenda_(itens);
  emitir_('meal_plan2', hexa);
  return { ok: true, gravado: hexa };
}

/* ============================ fotos ============================ */

function configFotos_() {
  return {
    ativas: prop_('FOTOS_ATIVAS') !== '0',
    minutosApos: Number(prop_('FOTO_MIN_APOS') || 2),
    intervaloMin: Number(prop_('FOTO_INTERVALO_MIN') || 0)
  };
}

function fotosConfig_(c) {
  if (typeof c.ativas !== 'boolean') throw erro_('campo ativas inválido');
  if (!inteiro_(c.minutosApos) || c.minutosApos < 0 || c.minutosApos > 30) throw erro_('minutos após a refeição: de 0 a 30');
  if (!inteiro_(c.intervaloMin) || c.intervaloMin < 0 || c.intervaloMin > 1440 || (c.intervaloMin > 0 && c.intervaloMin < 15)) {
    throw erro_('intervalo: 0 (desligado) ou de 15 a 1440 minutos');
  }
  PROPS.setProperties({ FOTOS_ATIVAS: c.ativas ? '1' : '0', FOTO_MIN_APOS: String(c.minutosApos), FOTO_INTERVALO_MIN: String(c.intervaloMin) });
  return { ok: true, config: configFotos_() };
}

/** Decide se há foto devida agora. Só lê o estado do comedouro (uma chamada à Tuya); não abre vídeo.
 *  `agora` (segundos) existe para teste; em uso normal fica vazio. */
function fotoDevida_(agora) {
  var cfg = configFotos_();
  if (!cfg.ativas) return { tirar: false, motivo: 'fotos desligadas' };
  var props = propriedades_();
  if (props.basic_private) return { tirar: false, motivo: 'modo privado ligado' };
  agora = agora || Math.floor(Date.now() / 1000);
  var ultima = null;
  try { ultima = JSON.parse(props.feed_record || 'null'); } catch (err) { /* sem registro */ }
  var refeicao = (ultima && ultima.time) || 0;
  var motivo = '';
  if (refeicao > Number(prop_('FOTO_ULTIMA_REFEICAO') || 0) && agora >= refeicao + cfg.minutosApos * 60 && agora - refeicao < 3 * 3600) {
    motivo = 'refeicao';
  } else if (cfg.intervaloMin > 0 && agora - Number(prop_('FOTO_ULTIMA_HORA') || 0) >= cfg.intervaloMin * 60) {
    motivo = 'rotina';
  }
  if (!motivo) return { tirar: false, motivo: 'nada pendente' };
  return { tirar: true, motivo: motivo, refeicao: refeicao };
}

/** O robô pergunta: é hora de tirar uma foto? Se for, já recebe o link do vídeo. */
function fotoPendente_() {
  var d = fotoDevida_();
  if (!d.tirar) return { ok: true, tirar: false, motivo: d.motivo };
  if (!tuya_('GET', '/v1.0/devices/' + dispositivo_()).online) return { ok: true, tirar: false, motivo: 'comedouro offline' };
  var url = tuya_('POST', '/v1.0/devices/' + dispositivo_() + '/stream/actions/allocate', { type: 'rtsp' }).url;
  return { ok: true, tirar: true, motivo: d.motivo, refeicao: d.refeicao, url: url };
}

/* ====================== agendador do Google ======================
   O agendador do GitHub chega a atrasar horas (ou pular execuções). O do Google é pontual:
   a cada 5 minutos ele confere se há foto devida e, só então, manda o GitHub rodar o robô na hora. */

function verificarFoto() {
  var token = prop_('GITHUB_TOKEN');
  if (!token) return;
  var d;
  try {
    d = fotoDevida_();
  } catch (err) {
    PROPS.setProperty('FOTO_ULTIMO_ERRO', 'Tuya: ' + String(err && err.message || err).slice(0, 160));
    return;
  }
  if (!d.tirar) return;
  var agora = Date.now();
  if (agora - Number(prop_('FOTO_DISPARO') || 0) < 10 * 60000) return;   // já chamou o robô há pouco
  var repo = prop_('GITHUB_REPO') || 'lffzdsf/capitufood';
  var resp = UrlFetchApp.fetch('https://api.github.com/repos/' + repo + '/actions/workflows/fotos.yml/dispatches', {
    method: 'post',
    contentType: 'application/json',
    muteHttpExceptions: true,
    headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'capitu-food' },
    payload: JSON.stringify({ ref: 'main' })
  });
  var cod = resp.getResponseCode();
  if (cod === 204) {
    PROPS.setProperties({ FOTO_DISPARO: String(agora), FOTO_ULTIMO_ERRO: '' });
  } else {
    var dica = cod === 401 ? ' (token inválido ou vencido)' : (cod === 403 || cod === 404) ? ' (token sem permissão neste repositório)' : '';
    PROPS.setProperty('FOTO_ULTIMO_ERRO', 'GitHub respondeu ' + cod + dica);
  }
}

/** Rode uma vez pelo editor para ligar o agendador (a cada 5 minutos). Pode rodar de novo sem duplicar. */
function instalarGatilho() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'verificarFoto') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('verificarFoto').timeBased().everyMinutes(5).create();
  Logger.log('Agendador ligado: verificarFoto roda a cada 5 minutos.');
}

function pastaFotos_() {
  var id = prop_('PASTA_FOTOS_ID');
  if (id) {
    try { return DriveApp.getFolderById(id); } catch (err) { /* pasta apagada: cria outra */ }
  }
  var pasta = DriveApp.createFolder(NOME_PASTA);
  PROPS.setProperty('PASTA_FOTOS_ID', pasta.getId());
  return pasta;
}

function indice_() {
  try { return JSON.parse(prop_('FOTO_INDICE') || '[]'); } catch (err) { return []; }
}

function fotoSalvar_(c) {
  var b64 = String(c.jpeg || '');
  if (b64.slice(0, 4) !== '/9j/' || b64.length > 4000000) throw erro_('imagem inválida');
  var motivo = c.motivo === 'refeicao' ? 'refeicao' : 'rotina';
  var agora = new Date();
  var nome = 'capitu-' + Utilities.formatDate(agora, Session.getScriptTimeZone(), 'yyyy-MM-dd_HH-mm-ss') + '-' + motivo + '.jpg';
  var arquivo = pastaFotos_().createFile(Utilities.newBlob(Utilities.base64Decode(b64), 'image/jpeg', nome));

  var indice = indice_();
  indice.unshift({ id: arquivo.getId(), nome: nome, t: Math.floor(agora.getTime() / 1000), motivo: motivo });
  var novas = { FOTO_INDICE: JSON.stringify(indice.slice(0, MAX_INDICE)), FOTO_ULTIMA_HORA: String(Math.floor(agora.getTime() / 1000)) };
  if (motivo === 'refeicao' && inteiro_(c.refeicao)) novas.FOTO_ULTIMA_REFEICAO = String(c.refeicao);
  PROPS.setProperties(novas);
  return { ok: true, id: arquivo.getId(), nome: nome };
}

function fotos_() {
  var id = prop_('PASTA_FOTOS_ID'), itens = indice_();
  return {
    ok: true,
    config: configFotos_(),
    itens: itens,
    pasta: id ? 'https://drive.google.com/drive/folders/' + id : '',
    diag: {
      gatilho: !!prop_('GITHUB_TOKEN'),
      disparo: Math.floor(Number(prop_('FOTO_DISPARO') || 0) / 1000),
      ultimaFoto: itens.length ? itens[0].t : 0,
      erro: prop_('FOTO_ULTIMO_ERRO')
    }
  };
}

function fotoVer_(id) {
  var conhecida = indice_().some(function (f) { return f.id === id; });
  if (!conhecida) throw erro_('foto não encontrada');
  var blob = DriveApp.getFileById(id).getBlob();
  return { ok: true, jpeg: Utilities.base64Encode(blob.getBytes()) };
}

/* ============================ utilidades ============================ */

function prop_(nome) { return PROPS.getProperty(nome) || ''; }
function inteiro_(v) { return typeof v === 'number' && isFinite(v) && Math.floor(v) === v; }
function erro_(msg, codigo) { var e = new Error(msg); e.codigo = codigo || 'erro'; return e; }
function json_(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }

function hex_(bytes) {
  return bytes.map(function (b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join('');
}
function sha256Hex_(texto) {
  return hex_(Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, texto, Utilities.Charset.UTF_8));
}
function hmacHex_(mensagem, chave) {
  return hex_(Utilities.computeHmacSha256Signature(mensagem, chave, Utilities.Charset.UTF_8));
}
/** Comparação que não vaza, pelo tempo de resposta, quantos caracteres estavam certos. */
function igual_(a, b) {
  var x = sha256Hex_(String(a)), y = sha256Hex_(String(b)), dif = 0;
  for (var i = 0; i < x.length; i++) dif |= x.charCodeAt(i) ^ y.charCodeAt(i);
  return dif === 0;
}

/**
 * Rode esta função uma vez pelo editor (Executar > testarConfiguracao) depois de preencher
 * as propriedades. Ela pede as permissões do Google e confirma que a Tuya responde.
 */
function testarConfiguracao() {
  var e = estado_();
  Logger.log('Comedouro: %s (%s) - %s', e.nome, e.modelo, e.online ? 'online' : 'offline');
  Logger.log('Pasta das fotos: %s', pastaFotos_().getUrl());
  Logger.log('SENHA_PAINEL definida: %s | TOKEN_ROBO definido: %s', !!prop_('SENHA_PAINEL'), !!prop_('TOKEN_ROBO'));
  Logger.log('GITHUB_TOKEN definido: %s | agendador ligado: %s', !!prop_('GITHUB_TOKEN'),
    ScriptApp.getProjectTriggers().some(function (t) { return t.getHandlerFunction() === 'verificarFoto'; }));
}
