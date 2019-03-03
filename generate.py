import pandas as pd
from pandas import DataFrame, Series
import logging
import os
import constants
import helpers
import json
import uuid
from functools import reduce


logging.basicConfig(
    level=logging.INFO,
    format='[%(module)s-l.%(lineno)s]%(asctime)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)


def get_party_item(sigla, df_c, df_p):
    if len(df_p[df_p['sigla_partido'] == sigla]) > 0:
        return df_p[df_p['sigla_partido'] == sigla].iloc[0]

    if len(df_c[df_c['sigla_partido'] == sigla]) > 0:
        return df_c[df_c['sigla_partido'] == sigla].iloc[0]    
    
    return {}


def use_in_reduce(acc: str, part: str):
    # primeira iteracao
    if len(acc) == 0:
        return acc + part.capitalize()
    
    # evitar que nomes com DA e DE, fique Da e De
    if part.upper() in ['DE', 'DA']:
        return acc + ' ' + part.lower()

    # iteracoes subsequentes
    return acc + ' ' + part.capitalize()


def normalize_nome(nome: str):
    if len(nome.split(' ')) == 1:
        return nome.capitalize()
    
    return reduce(
        use_in_reduce,
        nome.split(' '),
        ''
    )


def generate_candidate_data(candidate: Series, party_uuid: str, coeciente_eleitoral: int):
    return {
        'uuid': str(str(uuid.uuid4())),
        'party_uuid': str(party_uuid),
        'nome': normalize_nome(nome=candidate['nome']),
        'nome_urna': normalize_nome(nome=candidate['nome_urna']),
        'numero': int(candidate['numero_urna']),
        'votos': int(candidate['total_votos']),
        'sigla_partido': candidate['sigla_partido'],
        'sigla_uf': candidate['sigla_uf'],
        'composicao_legenda': candidate['composicao_legenda'],
        'nome_legenda': candidate['nome_legenda'],
        'ano_eleicao': int(candidate['ano_eleicao']),
        'puxado': int(candidate['total_votos']) <= coeciente_eleitoral,
        'state': candidate['descricao_totalizacao_turno']
    }


def generate_party_data(sigla: str, df_c: DataFrame, df_p: DataFrame, coligation_uuid: str, coeciente_eleitoral: int):
    logging.debug(f'Analisando o partido {sigla}')
    item = get_party_item(sigla=sigla, df_c=df_c, df_p=df_p)
    candidates = df_c[df_c['sigla_partido'] == sigla]
    legend_key = 'total_legenda'
    total_legenda = int(item[legend_key]) if legend_key in item.keys() else 0
    party_uuid = uuid.uuid4()

    return {
        'uuid': str(party_uuid),
        'coligacao_uuid': str(coligation_uuid),
        'nome': normalize_nome(nome=item['nome_partido']),
        'ano_eleicao': int(item['ano_eleicao']),
        'sigla_uf': item['sigla_uf'],
        'sigla': item['sigla_partido'],
        'numero': int(item['numero_partido']),
        'votos_nominais': int(sum(candidates['total_votos'])),
        'votos_legenda': total_legenda,
        'candidatos': [
            generate_candidate_data(candidate=candidate, party_uuid=party_uuid, coeciente_eleitoral=coeciente_eleitoral)
            for (_, candidate) in candidates.iterrows()
        ]
    }


def generate_coligation_data(coligation: str, df_c: DataFrame, df_p: DataFrame, state_uuid: str, coeciente_eleitoral: int):
    item = df_p[df_p['composicao_legenda'] == coligation].iloc[0]
    siglas = helpers.get_parties_by_coligation(coligation)

    logging.debug(f'Analisando a coligação {coligation}')
    logging.debug(f'Foram encontrados {len(siglas)} partidos')
    coligation_uuid = uuid.uuid4()

    return {
        'uuid': str(coligation_uuid),
        'state_uuid': str(state_uuid),
        'sigla_uf': item['sigla_uf'],
        'ano_eleicao': int(item['ano_eleicao']),
        'nome': normalize_nome(nome=item['nome_legenda']),
        'composicao': coligation,
        'partidos': [
            generate_party_data(
                sigla=sigla,
                df_c=df_c,
                df_p=df_p,
                coligation_uuid=coligation_uuid,
                coeciente_eleitoral=coeciente_eleitoral
            )
            for sigla in siglas
        ]
    }


def generate_date_for_state(state: str, df_c: DataFrame, df_p: DataFrame, ano: int, year_uuid: str):
    logging.info(f'Analizando o estado {state}')

    candidates_by_state = df_c[df_c['sigla_uf'] == state]
    parties_by_state = df_p[df_p['sigla_uf'] == state]

    logging.info(f'Foram encontrados {len(candidates_by_state)} candidatos em {len(parties_by_state)} partidos')

    cadeiras = len(candidates_by_state[candidates_by_state['descricao_totalizacao_turno'].isin(['ELEITO POR QP', 'ELEITO POR MEDIA'])])
    votos_nominais = int(sum(candidates_by_state['total_votos'])) + int(sum(parties_by_state['total_legenda']))

    coeciente_eleitoral = int(votos_nominais / cadeiras)

    state_uuid = uuid.uuid4()

    return {
        'uuid': str(state_uuid),
        'ano_uuid': str(year_uuid),
        'nome': normalize_nome(nome=candidates_by_state['descricao_ue'].iloc[0]),
        'sigla': state,
        'ano_eleicao': int(ano),
        'votos_nominais': votos_nominais,
        'cadeiras': cadeiras,
        'coligacoes': [
            generate_coligation_data(
                coligation=col,
                df_c=candidates_by_state,
                df_p=parties_by_state,
                state_uuid=state_uuid,
                coeciente_eleitoral=coeciente_eleitoral
            )
            for col in helpers.get_legend_composition(parties_by_state)
        ]
    }


def generate_ano_data(ano: int, df_c: DataFrame, df_p: DataFrame, res_json: list):
    year_uuid = uuid.uuid4()

    res_json.append({
        'ano': ano,
        'uuid': str(year_uuid),
        'estados': [
            generate_date_for_state(
                state=state,
                df_c=df_c[df_c['ano_eleicao'] == ano],
                df_p=df_p[df_p['ano_eleicao'] == ano],
                ano=ano,
                year_uuid=year_uuid
            )
            for state in helpers.get_states(df=df_c)
        ]
    })

def main():
    logging.info('Iniciando procedimento de geração dos dados para o banco')
    logging.info('Carregando os dados dos partidos')

    df_p = None
    df_c = None
    res_json = []

    if not os.path.exists(constants.PARTIDO_FILE_PATH):
        logging.info('Arquivo de partidos não existe')
        return None
    else:
        df_p = pd.read_csv(constants.PARTIDO_FILE_PATH)
    
    if not os.path.exists(constants.CANDIDATO_FILE_PATH):
        logging.info('Arquivo de candidatos não existe')
        return None
    else:
        df_c = pd.read_csv(constants.CANDIDATO_FILE_PATH)
    
    logging.info('Dados carregados')

    for ano in [2018]:
        generate_ano_data(
            ano=ano,
            df_c=df_c,
            df_p=df_p,
            res_json=res_json
        )
    
    with open(constants.JSON_OUTPUT_PATH, 'w') as fp:
        json.dump(res_json, fp, indent=2)

if __name__ == '__main__':
    main()
