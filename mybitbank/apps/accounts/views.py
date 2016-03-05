"""
The MIT License (MIT)

Copyright (c) 2016 Stratos Goudelis

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

"""

import datetime
import json
import forms

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect, HttpResponse
from django.shortcuts import render
from django.utils.timezone import utc
from django.utils.translation import ugettext as _

from models import addressAliases
from mybitbank.apps.addressbook.models import savedAddress
from mybitbank.libs import events, misc
from mybitbank.libs.config import MainConfig
from mybitbank.libs.connections import connector
from mybitbank.libs.entities import getWallets, getWalletByProviderId


current_section = 'accounts'

@login_required
def index(request):
    '''
    Handler for the accounts view
    '''
    
    # set the request in the connector object
    connector.request = request
    
    # get all wallets
    wallets = getWallets(connector)

    accounts = []
    for wallet in wallets:
        accounts_by_wallet = wallet.listAccounts(gethidden=True)
        accounts = accounts + accounts_by_wallet
    
    sections = misc.getSiteSections(current_section)
    
    page_title = _("Accounts")
    context = {
               'globals': MainConfig['globals'],
               'breadcrumbs': misc.buildBreadcrumbs(current_section, 'all'),
               'system_errors': connector.errors,
               'system_alerts': connector.alerts,
               'page_title': page_title,
               'page_sections': sections,
               'accounts': accounts,
               'request': request,
               }
    return render(request, 'accounts/index.html', context)

@login_required
def add(request):
    '''
    Handler for the account create form
    '''
    form = forms.CreateAccountForm()
    context = getAddAccountFormContext(form=form)
    context['breadcrumbs'] = misc.buildBreadcrumbs(current_section, '', 'Create')
    return render(request, 'accounts/add.html', context)

def getAddAccountFormContext(account_name='', error=None, form=None):
    '''
    Provide a common context between the account view and create account view
    '''
    # get available currencies
    providers_available = []
    providers = connector.config.keys()
    for provider_id in providers:
        providers_available.append({'id': provider_id, 'currency': connector.config[provider_id]['currency'], 'name': connector.config[provider_id]['name']})
        
    page_title = _("Create account")
    sections = misc.getSiteSections(current_section)
    context = {
               'globals': MainConfig['globals'],
               'system_alerts': connector.alerts,
               'system_errors': connector.errors,
               'breadcrumbs': misc.buildBreadcrumbs(current_section, '', 'Create'),
               'page_sections': sections,
               'page_title': page_title,
               'providers': providers_available,
               'account_name': account_name,
               'provider_id': provider_id,
               'error_message': error,
               'form': form,
               }
    return context

@login_required
def create(request):
    '''
    Handler for POST of create account form
    '''
    
    # set the request in the connector object
    connector.request = request
    
    if request.method == 'POST': 
        
        # we have a POST request
        form = forms.CreateAccountForm(request.POST)

        if form.is_valid(): 
            new_account_name = form.cleaned_data['account_name']
            provider_id = form.cleaned_data['provider_id']
            
            # all ok, create account
            new_address = connector.getNewAddress(provider_id, new_account_name)
            
            if new_address:
                messages.success(request, 'New account created with one address (%s)' % new_address, extra_tags="success")
                events.addEvent(request, 'Created new account with address "%s"' % (new_address), 'info')
                
            return HttpResponseRedirect(reverse('accounts:index'))

    else:
        form = forms.CreateAccountForm()
    
    context = getAddAccountFormContext(account_name="", form=form)
    return render(request, 'accounts/add.html', context)
    
    
def detailsCommonContext(request, provider_id, account_identifier, page=1):
    pass
    
    
@login_required        
def details_with_addresses(request, provider_id, account_identifier="pipes", page=1):
    '''
    Handler for the account details
    '''
    
    # set the request in the connector object
    connector.request = request
    
    provider_id = int(provider_id)
    
    # add a list of pages in the view
    sections = misc.getSiteSections(current_section)
    
    # get a wallet
    wallet = getWalletByProviderId(connector, provider_id)
    
    # get account details
    account = wallet.getAccountByIdentifier(account_identifier)
    
    page_title = _('Account details for "%s"') % (account['name'])
    
    context = {
               'globals': MainConfig['globals'],
               'request': request,
               'system_alerts': connector.alerts,
               'system_errors': connector.errors,
               'breadcrumbs': misc.buildBreadcrumbs(current_section, '', account['name']),
               'page_title': page_title,
               'active_tab': 'addresses',
               'current_page': page,
               'page_sections': sections,
               'wallet': wallet,
               'account': account,
               }
    
    return render(request, 'accounts/details.html', context)

@login_required        
def details_with_transactions(request, provider_id, account_identifier="pipes", page=1):
    '''
    Handler for the account details with transactions
    '''
    
    # set the request in the connector object
    connector.request = request
    
    transactions_per_page = 10
    provider_id = int(provider_id)
    page = int(page)
    
    # add a list of pages in the view
    sections = misc.getSiteSections(current_section)
    
    # get a wallet
    wallet = getWalletByProviderId(connector, provider_id)
    
    # get account details
    account = wallet.getAccountByIdentifier(account_identifier)
    
    transactions = []
    if account:
        # get transaction details
        transactions = account.listTransactions(limit=transactions_per_page, start=(transactions_per_page * (page - 1)))

    page_title = _('Account details for "%s"') % (account['name'])
    sender_address_tooltip_text = "This address has been calculated using the Input Script Signature. You should verify before using it."
    
    context = {
               'globals': MainConfig['globals'],
               'request': request,
               'system_alerts': connector.alerts,
               'system_errors': connector.errors,
               'breadcrumbs': misc.buildBreadcrumbs(current_section, '', account['name']),
               'page_title': page_title,
               'active_tab': 'transactions',
               'current_page': page,
               'next_page': (page + 1),
               'prev_page': max(1, page - 1),
               'levels': [(max(1, (page - 10)), max(1, (page - 100)), max(1, (page - 1000))), ((page + 10), (page + 100), (page + 1000))],
               'page_sections': sections,
               'wallet': wallet,
               'account': account,
               'transactions': transactions,
               'sender_address_tooltip_text': sender_address_tooltip_text,
               'transactions_per_page': transactions_per_page,
               }
    
    return render(request, 'accounts/details.html', context)
    
@login_required  
def setAddressAlias(request):
    '''
    Set address alias
    '''
    
    # set the request in the connector object
    connector.request = request
    
    return_msg = {'alias': ''}
    
    if request.method == 'POST':
        form = forms.SetAddressAliasForm(request.POST)
        if form.is_valid():
            # form is valid
            alias = form.cleaned_data['alias']
            address = form.cleaned_data['address']
            
            # check if address already has an alias, if multiple aliases exist for the same address, ignore them for now
            address_alias = addressAliases.objects.filter(address=address, status__gt=1)
            if address_alias:
                address_alias[0].alias = alias
                address_alias[0].save()
                events.addEvent(request, 'Updated alias for address "%s" to %s' % (address, alias), 'info')
            else:
                events.addEvent(request, 'Added alias "%s" for address "%s"' % (alias, address), 'info')
                address_alias = addressAliases.objects.create(address=address, alias=alias, status=2, entered=datetime.datetime.utcnow().replace(tzinfo=utc))
            
            if address_alias:
                return_msg = {'alias': alias}
            else:
                return_msg = {'alias': 'sugnomi xasate'}
                
    json_str = json.dumps(return_msg)             
    return HttpResponse(json_str, mimetype="application/x-javascript")

@login_required
def createNewAddress(request, provider_id, account_identifier):
    '''
    Create a new address for the account of account_identifier
    '''
    
    # set the request in the connector object
    connector.request = request
    
    provider_id = int(provider_id)
    wallet = getWalletByProviderId(connector, provider_id)
    if request.method == 'POST': 
        account = wallet.getAccountByIdentifier(account_identifier)
        if account:
            new_address = connector.getNewAddress(account['provider_id'], account['name'])
            messages.success(request, 'New address "%s" created for account "%s"' % (new_address, account['name']), extra_tags="success")
            events.addEvent(request, 'New address "%s" created for account "%s"' % (new_address, account['name']), 'info')
        return HttpResponseRedirect(reverse('accounts:details_with_addresses', kwargs={'provider_id': provider_id, 'account_identifier': account_identifier, 'page': 1}))
    
    
