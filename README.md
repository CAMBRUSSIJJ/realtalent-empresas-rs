# RealTalent Empresas RS

Dashboard histórico e consulta individual da base estadual da Receita Federal. O workflow Importar base estadual RS baixa os dez arquivos nacionais do espelho Casa dos Dados e publica uma release somente após validar 497 municípios, contagens e unicidade dos CNPJs. O repositório e as releases são públicos; não há controle de acesso aos arquivos. Não são publicados telefone, e-mail, endereço, CPF ou QSA. A base contém os campos selecionados de estabelecimentos, não todas as colunas da Receita. Os indicadores históricos não são recalculados.

## Vercel
Importe este repositório no projeto de dashboard, framework Other, output public, diretório raiz do repo. A API Python lê as releases públicas deste repo por padrão. GH_DATA_TOKEN opcional (somente leitura) para ampliar a franquia da API GitHub; SEARCH_ACCESS_CODE opcional para proteger a API, mas não os downloads públicos da release. Não coloque segredos no Git. GH_DATA_TAG opcional para fixar uma versão. Consulte a aba Consultar empresas depois da primeira release bem-sucedida. GitHub Actions, Vercel e GitHub API têm limites; custo zero não é garantido. 
