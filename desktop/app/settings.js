const form = document.querySelector('form');
const key = document.querySelector('#key');
const save = form.querySelector('[type=submit]');
const remove = document.querySelector('#remove');
const message = document.querySelector('#status');

function show(status) {
  if (!status) {
    message.textContent = 'The local API is unavailable. Reopen Settings after Argus starts.';
    return;
  }
  if (status.mode === 'starting') {
    message.textContent = 'Argus is starting…';
    setTimeout(refresh, 500);
    return;
  }
  save.disabled = false;
  remove.disabled = status.mode !== 'live' && !status.keychainUnavailable;
  message.textContent = status.mode === 'live'
    ? 'The simulated shop is running with the live agent.'
    : 'The simulated shop is running with the sealed replay agent.';
  if (status.keychainUnavailable) message.textContent += ' The system credential store could not be read.';
}

async function refresh() {
  try {
    show(await window.argusSettings.status());
  } catch {
    show(null);
  }
}

async function change(value) {
  const removeWasDisabled = remove.disabled;
  save.disabled = true;
  remove.disabled = true;
  message.textContent = 'Updating the credential and restarting the local API…';
  try {
    const status = await window.argusSettings.changeKey(value);
    if (!status || status.error) throw new Error(status?.error ?? 'The credential could not be updated.');
    show(status);
  } catch (error) {
    message.textContent = error.message;
    save.disabled = false;
    remove.disabled = removeWasDisabled;
  }
}

form.addEventListener('submit', (event) => {
  event.preventDefault();
  const value = key.value.trim();
  key.value = '';
  if (!/^[!-~]{1,512}$/.test(value)) {
    message.textContent = 'Enter an API key without spaces.';
    return;
  }
  void change(value);
});
remove.addEventListener('click', () => void change(null));
void refresh();
