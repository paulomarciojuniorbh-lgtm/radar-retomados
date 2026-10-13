# Radar Retomados

Imóveis retomados de bancos (leilões) ranqueados por oportunidade.

- `index.html`: o radar. Lê os imóveis coletados diariamente (Supabase) e calcula a nota de 0 a 100.
- `convite.html`: página do programa de testadores.
- `dados.json`: foto dos dados, usada só se a leitura ao vivo falhar.

A coleta diária roda numa função do Supabase (`radar-coleta-mega`), agendada para 6h40 (horário de Brasília).
