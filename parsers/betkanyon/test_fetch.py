from parsers.betkanyon.fetcher import BetkanyonFetcher
from parsers.betkanyon.decryptor import BetkanyonDecryptor


fetcher = BetkanyonFetcher()

decryptor = BetkanyonDecryptor()

while True:

    encrypted = fetcher.fetch()

    print("Decrypting...")

    decrypted = decryptor.decrypt(encrypted)

    print()

    print("Keys:")

    print(decrypted.keys())

    print()

    print("Waiting for next update...\n")