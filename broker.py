import httpx

from abc import ABC, abstractmethod
from enum import Enum
from httpx import codes
from typing import Collection, List
from pydantic import BaseModel


class Position(BaseModel):
    name: str
    size: int

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if isinstance(other, Position):
            return self.name == other.name
        elif isinstance(other, str):
            return self.name == other


class OrderStatus(Enum):
    OPEN = 'open'
    FILLED = 'filled'
    REJECTED = 'rejected'
    EXPIRED = 'expired'
    CANCELED = 'canceled'
    PENDING = 'pending'
    PARTIALLY_FILLED = 'partially_filled'
    CALCULATED = 'calculated'
    ACCEPTED_FOR_BIDDING = 'accepted_for_bidding'
    ERROR = 'error'
    HELD = 'held'


class Order(BaseModel):
    id: str
    name: str
    side: str
    status: OrderStatus
    executed_quantity: int
    avg_fill_price: float


class Broker(ABC):

    def __init__(self, account_number: str):
        self._account_number = account_number

    @property
    @abstractmethod
    async def positions(self) -> List[Position]:
        pass


class Tradier(Broker):

    def __init__(self, account_number: str, **kwargs):

        super().__init__(account_number)

        access_token = kwargs.get('access_token')
        if access_token is None:
            raise ValueError(
                'must have an access token to instantiate Tradier broker'
            )

        self._headers = dict(
            Accept='application/json',
            Authorization=f'Bearer {access_token}'
        )

    def _form_url(self, endpoint):

        tradier_api = 'api.tradier.com'
        tradier_api_version = 'v1'

        if tradier_api is None or tradier_api_version is None:
            raise EnvironmentError(
                'TRADIER_API and TRADIER_API_VERSION cannot be null'
            )

        base = f'https://{tradier_api}/{tradier_api_version}'
        components = (base, endpoint)
        almost_there = '/'.join(x.strip('/') for x in components)
        complete_url = almost_there.replace(
            '[[account]]',
            self._account_number
        )

        return complete_url

    @property
    def positions(self) -> List[Position]:

        with httpx.Client() as client:
            response = client.get(
                url=self._form_url('/accounts/[[account]]/positions/'),
                headers=self._headers
            )

        if response.status_code != httpx.codes.OK:
            raise IOError(
                f'failed to get account positions for account '
                f'{self._account_number} with a status code of '
                f'{response.status_code}: {response.text}'
            )

        if response.json()['positions'] in (None, 'null'):
            return list()

        positions = response.json()['positions']['position']

        if isinstance(positions, list):

            return [
                Position(name=pos['symbol'], size=pos['quantity'])
                for pos in positions
            ]

        else:

            return [Position(
                name=positions['symbol'],
                size=positions['quantity']
            )]
