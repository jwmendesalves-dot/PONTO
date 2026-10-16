// ui-kit.js — toasts e confirmações do Ponto Digital (substitui alert/confirm nativos).
function toast(msg, tipo = "ok") {
  let caixa = document.getElementById("ui-toasts");
  if (!caixa) {
    caixa = document.createElement("div");
    caixa.id = "ui-toasts";
    document.body.appendChild(caixa);
  }
  const el = document.createElement("div");
  el.className = "toast " + tipo;
  el.textContent = msg;
  caixa.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function confirmarAcao({ titulo = "Confirmar", texto = "", confirmar = "Confirmar", cancelar = "Cancelar" } = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-label="' + titulo.replace(/"/g, "&quot;") + '">' +
      '<h3></h3><p></p><div class="modal-acoes"></div></div>';
    overlay.querySelector("h3").textContent = titulo;
    overlay.querySelector("p").textContent = texto;
    const acoes = overlay.querySelector(".modal-acoes");
    const btnNao = document.createElement("button");
    btnNao.className = "btn btn-ghost";
    btnNao.textContent = cancelar;
    const btnSim = document.createElement("button");
    btnSim.className = "btn btn-primary";
    btnSim.textContent = confirmar;
    const fechar = (v) => { overlay.remove(); resolve(v); };
    btnNao.addEventListener("click", () => fechar(false));
    btnSim.addEventListener("click", () => fechar(true));
    acoes.append(btnNao, btnSim);
    document.body.appendChild(overlay);
    btnSim.focus();
  });
}
