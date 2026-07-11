# TeIA — Princípios da Marca

> Guideline de decisão para qualquer ação realizada neste repositório (código, conteúdo, produto, comunicação). Sempre que houver dúvida sobre como proceder, verificar contra os princípios abaixo antes de decidir.
> Complementa [brand.md](./brand.md) (identidade visual e linguajar).

---

## 1. Princípios inegociáveis (do manifesto)

1. **A tecnologia deve servir à missão.**
   Nenhuma feature, automação ou decisão de produto deve existir "porque é possível" — precisa servir ao propósito institucional do cliente/organização final.

2. **As decisões continuam sendo humanas.**
   Toda solução construída aqui é **human-in-the-loop** por padrão. Nunca projetar um fluxo onde a IA publica, decide ou age sem um ponto de revisão/aprovação humana.

3. **Impacto continua sendo o objetivo final.**
   Métrica de sucesso não é "quanto conteúdo a IA gerou", mas o efeito real na capacidade da organização de cumprir sua missão.

4. **"A IA sugere. A equipe decide."**
   Princípio de design de qualquer interface, workflow ou automação: a IA propõe, sugere, rascunha — nunca finaliza ou publica sem confirmação humana explícita.

---

## 2. Princípios operacionais

- **Camada obrigatória de auditoria humana**: qualquer sistema/fluxo de IA construído deve ter um passo de revisão humana antes da entrega final ou publicação. Isso não é opcional nem configurável para "off".
- **Soberania e propriedade de dados**: contas, chaves de API e dados de IA pertencem à organização cliente, não à TeIA. Nunca desenhar arquitetura que centralize dados ou credenciais do cliente em infraestrutura da TeIA sem necessidade técnica explícita e consentida.
- **Personalização sobre padronização**: soluções devem ser calibradas à voz e ao contexto institucional de cada organização — evitar templates genéricos que ignoram a identidade de quem está sendo atendido.
- **Aprendizado institucional como entrega**: todo projeto/funcionalidade deve gerar documentação, capacitação ou evidência reaproveitável pela organização — não apenas um artefato técnico fechado ("caixa-preta").
- **Abordagem faseada e incremental**: diagnóstico → estruturação/capacitação → implementação assistida → avaliação. Evitar "big bang": preferir entregas que gerem valor imediato e constroem a base para a próxima etapa.
- **Fluência em IA como parte da entrega**: capacitar a equipe do cliente (ou do usuário) para usar e entender a ferramenta com segurança é parte do produto, não um extra.

---

## 3. Princípios de tom e comunicação (aplicáveis a qualquer texto gerado no repo)

- Falar como quem **vem do setor de impacto**, não como fornecedor de tecnologia genérico.
- Nunca vender a IA como solução mágica ou substituta de julgamento humano.
- Preferir clareza e precisão sobre jargão técnico não traduzido (exceção: termos consagrados como *human-in-the-loop*).
- Qualquer copy, mensagem de erro, onboarding ou documentação deve refletir o vocabulário-âncora da marca (propósito, impacto, missão, capacidades humanas, supervisão) — ver [brand.md §3.2](./brand.md#32-vocabulário-âncora).
- Evitar linguagem de hype, growth-hacking ou urgência artificial.

---

## 4. Checklist rápido antes de qualquer entrega

- [ ] Existe um ponto de revisão/aprovação humana no fluxo?
- [ ] A solução está calibrada à voz/contexto da organização atendida, ou é genérica?
- [ ] Dados e credenciais permanecem sob propriedade do cliente?
- [ ] A entrega deixa algum aprendizado ou capacitação para a organização, além do artefato técnico?
- [ ] O texto/copy evita hype e usa o vocabulário-âncora da marca?
- [ ] A decisão de produto serve à missão do cliente, ou apenas demonstra capacidade técnica?
