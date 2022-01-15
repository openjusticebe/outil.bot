#!/usr/bin/env python3
#  OutilBot
#     Copyright (C) 2022 OpenJustice.be - Pieterjan Montens
#     This program is free software: you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation, either version 3 of the License, or
#     (at your option) any later version.
#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#     GNU General Public License for more details.
#     You should have received a copy of the GNU General Public License
#     along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

import click
import sys
import logging
import os
import time
import math
import asyncio
import httpx
import json
import time
import datetime
from httpx_auth import OAuth2AuthorizationCode

logger = logging.getLogger(__name__)
logger.setLevel(logging.getLevelName('INFO'))
logger.addHandler(logging.StreamHandler())

config = {
    'api_user': os.getenv('USER'),
    'api_pass': os.getenv('PASSWORD'),
    'input_dir' : os.getenv('INPUT_DIR'),
    'auth_api' : os.getenv('AUTH_API','http://127.0.0.1:5015'),
    'anon_api' : os.getenv('ANON_API','http://127.0.0.1:5011'),
    'data_api' : os.getenv('DATA_API', 'http://127.0.0.1:5010'),
    'scope_url' : os.getenv('SCOPE', 'localhost'),
    'anonymise' : os.getenv('ANONYMISE', True),
}


@click.group()
@click.option('--debug', '-d', 'debug', is_flag=True, default=False,
              help="Activate debugging flag")
@click.option('--dry-run', '-r', 'dryrun', is_flag=True, default=False,
              help="Do a dry run (don't really persist anything)")
@click.pass_context
def run(ctx, debug, dryrun):
    ctx.ensure_object(dict)
    ctx.obj['DEBUG'] = debug
    ctx.obj['DRYRUN'] = debug
    if debug:
        logger.setLevel(logging.getLevelName('DEBUG'))
        logger.info('Debugging Enabled')
    if dryrun:
        logger.warning('/!\\ This is a DRY-RUN /!\\')


@run.command()
def test():
    """
    Run a quick auth / anon / upload test
    """
    logger.info("Doing test run")
    filePath = "./misc/test_fr_7.pdf"

    # ################################################# # Step 1 : get content
    logger.info("test run")
    files = {'rawFile': open(filePath, 'rb')}
    r = httpx.post(
        f"{config['anon_api']}/extract/",
        headers={'Accept': 'application/json'},
        files=files)
    step1 = r.json()
    logger.info('Received Ref: %s', step1['ref'])

    loop = 0
    meta = {}
    text = []
    time.sleep(2)
    page_rec = 0
    page_tot = 0

    while True:
        if loop > 10 :
            raise RuntimeError("Exceeded allowed loop count, file failed")
        loop += 1

        r = httpx.get(
            f"{config['anon_api']}/extract/status",
            headers={'Accept': 'application/json'},
            params={'ref': step1['ref']}
        )
        step2 = r.json()

        if step2['status'] == 'error':
            logger.critical(step2['value'])
            raise RuntimeError("Failed data extract : %s", step2['value'])

        elif step2['status'] == 'meta':
            meta = step2['value']
            page_tot = meta['pages']
            logging.info('Received meta, total pages expected: %s', page_tot)
            if step2['value']['doOcr']:
                logging.info('OCR Operation ongoing')

        elif step2['status'] == 'page':
            page_rec += 1
            text[int(step2['value']['page'])] = step2['value']['text']

        elif step2['status'] == 'text':
            text.append(step2['value'])
            page_rec = page_tot

        elif step2['status'] == 'empty':
            if page_tot == page_rec:
                break

        time.sleep(2)

    text = ''.join(text)

    logger.info('Received data, anonymizing')

    # ################################################### # Step 1 : Anonymise
    payload={
        '_v': 1,
        '_timestamp': int(datetime.datetime.now().timestamp()),
        'algo_list': [
            { 'id': 'anon_trazor', 'params': json.dumps({'method':'brackets'})},
            { 'id':'anon_mask', 'params': '{}' }
        ],
        'format': 'text',
        'encoding': 'utf8',
        'text': text,
        'anon_log': False,
        'error': False,
        }
    r = httpx.post(
        f"{config['anon_api']}/run",
        headers={'Content-Type' : 'application/json', 'Accept': 'application/json'},
        json=payload
    )
    step3 = r.json()

    if 'error' in step3['log']:
        logger.critical(step3['log'])
        raise RuntimeError('Failed anonymizing operation')

    text = step3['text']

    logger.info('Received anonymized version, uploading')

    ###################################################### # Step 1 : Upload
    
    login_payload = {
        'grant_type': 'password',
        'username':config['api_user'],
        'password':config['api_pass'],
        'scope':f'host:{config["scope_url"]}',
        'client_id':'',
        'client_secret':''
    }

    r = httpx.post(
        f"{config['auth_api']}/token",
        headers={
            'Content-Type' : 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        },
        data=login_payload
    )

    auth = r.json()
    if 'access_token' not in auth:
        raise RuntimeError('Failed Auth')
    logger.info('User token obtained')

    payload = {
        '_v': 1,
        '_timestamp': int(datetime.datetime.now().timestamp()),
        'country' : 'BE',
        'court' : '',
        'year' : 2000,
        'identifier' : '',
        'text': text,
        'lang': 'FR',
        'labels': [],
        'appeal' : 'nodata',
        'user_key': '',
        'doc_links': []
    }
    headers_payload = {
        'Content-Type' : 'application/json',
        'Accept': 'application/json',
        'Authorization': f'{auth["token_type"]} {auth["access_token"]}'
    }

    r = httpx.post(
        f'{config["data_api"]}/create',
        headers = headers_payload,
        data = json.dumps(payload)
    )
    step4 = r.json()
    if step4['result'] == 'ok':
        logger.info('Upload succeeded')
        logger.info('Hash: %s', step4['hash'])
        logger.info('URL : %s/hash/%s', config['data_api'], step4['hash'])

if __name__ == "__main__":
    run()
