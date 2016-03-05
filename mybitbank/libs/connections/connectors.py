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
import hashlib
import signal
import time
import mybitbank.libs.jsonrpc

from httplib import CannotSendRequest
from django.utils.timezone import utc

from mybitbank.libs import events
from mybitbank.libs import misc
from mybitbank.libs.bitcoinrpc.authproxy import JSONRPCException
from mybitbank.libs.jsonrpc import ServiceProxy
#from mybitbank.libs.entities.cacher import Cacher


measure_time = False


def timeit(method):
    if measure_time is not True:
        return method
    
    def timed(*args, **kw):
        ts = time.time()
        result = method(*args, **kw)
        te = time.time()

        print '%r() (%r, %r) %2.2f sec' % (method.__name__, args, kw, te - ts)
        return result

    return timed


class ExecuteCommandTimeoutException(Exception):
    '''
    WIP! Do not use!
    '''
    pass 


class Connector(object):
    # signal timeout
    signal_timeout = 3
    
    # how long to disable a failing service
    disable_time = 10
    
    # currency providers config
    config = {}
    
    # ServiceProxies objects
    services = {}
    
    # errors 
    errors = []
    
    # alerts shown on the UI as alerts
    alerts = {}
    
    # the WSGIRequest object we are serving
    request = None
    
    # cache object
    cache = []
    
    @timeit
    def __init__(self):
        '''
        Constructor, load config 
        '''
        
        mybitbank.libs.jsonrpc.HTTP_TIMEOUT = 2
        
        try:
            import walletconfig
            currency_configs = walletconfig.config
        except (AttributeError, ImportError) as e:
            self.errors.append({'message': 'Error occurred while loading the wallet configuration file (%s)' % (e), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})

        for currency_config in currency_configs:
            if currency_config.get('enabled', True):
                self.config[currency_config['id']] = currency_config
                self.config[currency_config['id']]['enabled'] = True
                self.services[currency_config['id']] = ServiceProxy("http://%s:%s@%s:%s" % 
                                                         (currency_config['rpcusername'],
                                                          currency_config['rpcpassword'],
                                                          currency_config['rpchost'],
                                                          currency_config['rpcport']))

    def executeCommand(self, provider_id, command, *args):
        '''
        WIP! Do not use. This does not work when outside main thread!
        
        Call the command from the currency provider (xxxcoinds) with timeout signals
        since the xxxcoinds may accept the connection but will not respond because they are busy. 
        They can be busy for many reasons. Some calls block the RCP threads or they could be downloading 
        blocks. This make the httplib timeout useless. Using signals we can timeout any function regardless
        of the reason it is delaying.
        '''
        
        print "provider_id: %s" % provider_id
        print "command: %s" % command
        print args
        
        def timeout_handler(signum, frame):
            raise ExecuteCommandTimeoutException()
        
        old_handler = signal.signal(signal.SIGALRM, timeout_handler) 
        signal.alarm(self.signal_timeout)
        
        try: 
            rpc_method = getattr(self.services[provider_id], command)
            rpc_response = rpc_method(*args)
            print rpc_response
        except ExecuteCommandTimeoutException:
            print "timeout"
            self.errors.append({'message': 'Signal timeout occurred while doing %s (provider id: %s)' % (command, provider_id), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})
            self.removeCurrencyService(provider_id)
            return None
        finally:
            print "finally"
            signal.signal(signal.SIGALRM, old_handler) 
        
        print "returning"
        signal.alarm(0)
        return rpc_response

    def addAlert(self, category, alert):
        '''
        Add an alert for the UI
        '''
        if self.alerts.get(category, True) is True:
            self.alerts[category] = []
        
        self.alerts[category].append(alert)
        return True
    
    @timeit
    def removeCurrencyService(self, provider_id):
        '''
        Remove the ServiceProxy object from the list of service in case of a xxxcoind daemon not responding in time
        '''
        if self.config.get(provider_id, False):
            currency_provider_config = self.config.get(provider_id, {})
            if currency_provider_config.get('enabled', False) is True:
                self.addAlert('currencybackend', {'provider_id': provider_id, 'message': 'Currency service provider %s named %s is disabled for %s seconds due an error communicating.' % (provider_id, currency_provider_config['name'], self.disable_time), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})
                currency_provider_config['enabled'] = datetime.datetime.utcnow().replace(tzinfo=utc) + datetime.timedelta(0, self.disable_time)
                events.addEvent(self.request, "Currency service %s has being disabled for %s seconds due to error communicating" % (currency_provider_config['currency'], self.disable_time), 'error')
                if self.services.get(provider_id, None):
                    del self.services[provider_id]

    def longNumber(self, x):
        '''
        Convert number coming from the JSON-RPC to a human readable format with 8 decimal
        '''
        if type(x) is str:
            return x
        else:
            return "{:.8f}".format(x)
    
    def getParamHash(self, param=""):
        '''
        This function takes a string and calculates a sha224 hash out of it. 
        It is used to hash the input parameters of functions/method in order to 
        uniquely identify a cached result based  only on the input parameters of 
        the function/method call.
        '''
        cache_hash = hashlib.sha224(param).hexdigest()
        return cache_hash
    
    @timeit
    def getInfo(self, provider_id):
        '''
        Get xxxcoind info
        '''
        
        if provider_id not in self.services.keys():
            return {'message': 'Non-existing currency provider id %s' % provider_id, 'code':-100}
        
        peerinfo = {}
        try:
            if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
                peerinfo = self.services[provider_id].getinfo()
        except (JSONRPCException, Exception), e:
            self.errors.append({'message': 'Error occurred while doing getinfo (provider id: %s, error: %s)' % (provider_id, e), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})
            self.removeCurrencyService(provider_id)
        
        return peerinfo
    
    @timeit
    def getPeerInfo(self, provider_id):
        '''
        Get peer info from the connector (xxxcoind)
        '''
        peers = []
        try:
            if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
                peers = self.services[provider_id].getpeerinfo()
        except JSONRPCException:
            # in case coind not support getpeerinfo command
            return {'error'} 
        except Exception, e:
            # in case of an error, store the error, disabled the service and move on
            self.errors.append({'message': 'Error occurred while doing getpeerinfo (provider id: %s, error: %s)' % (provider_id, e), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})
            self.removeCurrencyService(provider_id)
            
        return peers
    
    @timeit
    def listAccounts(self, gethidden=False, getarchived=False, selected_provider_id=-1):
        '''
        Get a list of accounts. This method also supports filtering, fetches address for each account etc.
        '''
        
        # get data from the connector (xxxcoind)
        fresh_accounts = {}
        
        if selected_provider_id > 0:
            provider_ids = [int(selected_provider_id)]
        else:
            provider_ids = self.config.keys()
        
        for provider_id in provider_ids:
            if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
                try:
                    fresh_accounts[provider_id] = self.services[provider_id].listaccounts()
                    for fresh_account_name, fresh_account_balance in fresh_accounts[provider_id].items():
                        fresh_accounts[provider_id][fresh_account_name] = self.longNumber(fresh_account_balance)
                except (Exception, CannotSendRequest) as e:
                    # in case of an error, store the error, remove the service and move on
                    self.errors.append({'message': 'Error occurred while doing listaccounts (provider id: %s, error: %s)' % (provider_id, e), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})
                    self.removeCurrencyService(provider_id)
                    
        return fresh_accounts
    
    @timeit
    def getAddressesByAccount(self, account, provider_id):
        '''
        Get the address of an account name
        '''
        
        if type(account) in [str, unicode]:
            name = account
        elif account.get('name', False):
            name = account['name']
        else:
            return []
            
        addresses = []
        if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
            try:
                addresses = self.services[provider_id].getaddressesbyaccount(name)
            except Exception, e:
                self.errors.append({'message': 'Error occurred while doing getaddressesbyaccount (provider id: %s, error: %s)' % (provider_id, e), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})
                self.removeCurrencyService(provider_id)

        return addresses
    
    @timeit
    def listTransactionsByAccount(self, account_name, provider_id, limit=100000, start=0):    
        '''
        Get a list of transactions by account name and provider_id
        '''
        
        transactions = []
        if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
            try:
                transactions = self.services[provider_id].listtransactions(account_name, limit, start)
            except Exception as e:
                self.errors.append({'message': 'Error occurred while doing listtransactions (provider_id: %s, error: %s)' % (provider_id, e), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})
                self.removeCurrencyService(provider_id)
            
        return transactions
    
    @timeit
    def getNewAddress(self, provider_id, account_name):
        '''
        Create a new address
        '''
        new_address = None
        
        if provider_id not in self.config.keys():
            return False
        
        if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
            if self.services.get(provider_id, False) and type(account_name) in [str, unicode]:
                new_address = self.services[provider_id].getnewaddress(account_name)
                return new_address
        else:
            return False
    
    @timeit
    def getBalance(self, provider_id=0, account_name="*"):
        '''
        Get balance for each provider
        '''
        balances = {}
        
        if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
            try:
                balances[provider_id] = self.services[provider_id].getbalance(account_name)
            except Exception as e:
                # in case of an Exception continue on to the next currency service (xxxcoind)
                self.errors.append({'message': 'Error occurred while doing getbalance (provider id: %s, error: %s)' % (provider_id, e), 'when': datetime.datetime.utcnow().replace(tzinfo=utc)})
                self.removeCurrencyService(provider_id)
        
        return balances
   
    @timeit
    def moveAmount(self, from_account, to_account, provider_id, amount, minconf=1, comment=""):
        '''
        Move amount from local to local accounts
        Note: from_account my be an empty string 
        '''
        if provider_id not in self.services.keys():
            return {'message': 'Non-existing currency provider id %s' % provider_id, 'code':-100}
        
        if self.config[provider_id]['enabled'] is not True:
            return {'message': 'Currency service with id %s disabled for now' % provider_id, 'code':-150}
        
        if not misc.isFloat(amount) or type(amount) is bool:
            return {'message': 'Amount is not a number', 'code':-102}
        
        if type(comment) not in [str, unicode]:
            return {'message': 'Comment is not valid', 'code':-104}
        
        try:
            minconf = int(minconf)
        except:
            return {'message': 'Invalid minconf value', 'code':-105}
        
        account_list = self.services[provider_id].listaccounts()

        account_names = []
        for account_name in account_list:
            account_names.append(account_name)
        
        if from_account in account_names and to_account in account_names:
            # both accounts have being found, perform the move
            try:
                reply = self.services[provider_id].move(from_account, to_account, amount, minconf, comment)
            except JSONRPCException, e: 
                return e.error
            except ValueError, e:
                return {'message': e, 'code':-1}
            
            return reply
        else:
            # account not found
            return {'message': 'source or destination account not found', 'code':-103}
    
    @timeit          
    def sendFrom(self, from_account, to_address, amount, provider_id, minconf=1, comment="", comment_to=""):
        if type(from_account) not in [str, unicode]:
            return {'message': 'Invalid input from account', 'code':-156}
        
        if not to_address or not provider_id:
            return {'message': 'Invalid input to account or address', 'code':-101}

        if provider_id not in self.services.keys():
            return {'message': 'Non-existing currency provider id %s' % provider_id, 'code':-100}

        if not misc.isFloat(amount) or type(amount) is bool:
            return {'message': 'Amount is not a number', 'code':-102}

        if type(comment) not in [str, unicode]  or type(comment_to) not in [str, unicode]:
            return {'message': 'Comment is not valid', 'code':-104}
        
        account_list = self.services[provider_id].listaccounts()
        
        account_names = []
        for account_name in account_list:
            account_names.append(account_name)
            
        if from_account in account_names:
            # account given exists, continue
            try:
                reply = self.services[provider_id].sendfrom(from_account, to_address, amount, minconf, comment, comment_to)
            except JSONRPCException, e:
                return e.error
            except ValueError, e:
                return {'message': e, 'code':-1}
            except Exception, e: 
                return e
            
            return reply
        else:
            # account not found
            return {'message': 'Source account not found', 'code':-106}

    @timeit
    def getRawTransaction(self, txid, provider_id):
        '''
        Return transaction details, like sender address
        '''

        if provider_id not in self.config.keys():
            return {'message': 'Non-existing currency provider id %s' % provider_id, 'code':-121}
        
        if self.config[provider_id]['enabled'] is not True:
            return {'message': 'Currency service %s disabled for now' % provider_id, 'code':-150}
        
        if type(txid) not in [str, unicode] or not len(txid):
            return {'message': 'Transaction ID is not valid', 'code':-127} 
        
        transaction_details = None
        try:
            if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
                transaction_details = self.services[provider_id].getrawtransaction(txid, 1)
        except JSONRPCException:
            return {}
        except Exception:
            return {}
        
        return transaction_details
    
    @timeit
    def decodeRawTransaction(self, transaction, provider_id):
        '''
        Decode raw transaction
        '''
        if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
            return self.services[provider_id].decoderawtransaction(transaction)
    
    @timeit
    def getTransaction(self, txid, provider_id):
        '''
        Return a transaction
        '''
        if provider_id not in self.config.keys():
            return {'message': 'Non-existing currency provider id %s' % provider_id, 'code':-121}
        
        if self.config[provider_id]['enabled'] is not True:
            return {'message': 'Currency service provider id %s disabled for now' % provider_id, 'code':-150}
        
        if type(txid) not in [str, unicode] or not len(txid):
            return {'message': 'Transaction ID is not valid', 'code':-127} 
        
        transaction_details = None
        try:
            if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
                transaction_details = self.services[provider_id].gettransaction(txid)
        except JSONRPCException:
            return {}
        except Exception:
            return {}
    
        return transaction_details
    
    @timeit
    def walletPassphrase(self, passphrase, provider_id):
        '''
        Unlock the wallet
        '''

        if type(passphrase) not in [str, unicode]:
            return {'message': 'Incorrect data type for passphrase', 'code':-110}
        
        if len(passphrase) < 1:
            return {'message': 'No passphrase given', 'code':-111}
        
        if provider_id not in self.services.keys():
            return {'message': 'Invalid non-existing or disabled currency', 'code':-112}
        
        if self.config[provider_id]['enabled'] is not True:
            return {'message': 'Currency service provider id %s disabled for now' % provider_id, 'code':-150}
        
        try:
            if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
                unload_exit = self.services[provider_id].walletpassphrase(passphrase, 30)
            else:
                return False
        except JSONRPCException, e:
            return e.error
        except Exception, e:
            return e.error
         
        if type(unload_exit) is dict and unload_exit.get('code', None) and unload_exit['code'] < 0:
            # error occurred
            return unload_exit
        else:
            return True
    
    @timeit    
    def walletLock(self, provider_id):
        '''
        Lock wallet
        '''
        if provider_id not in self.services.keys():
            return {'message': 'Invalid non-existing or disabled currency', 'code':-112}
        
        if self.config.get(provider_id, False) and self.config[provider_id]['enabled'] is True:
            self.services[provider_id].walletlock()
        
