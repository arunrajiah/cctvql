import { ICredentialType, INodeProperties } from 'n8n-workflow';

export class CctvqlApi implements ICredentialType {
	name = 'cctvqlApi';
	displayName = 'cctvQL API';
	documentationUrl = 'https://github.com/arunrajiah/cctvql';
	properties: INodeProperties[] = [
		{
			displayName: 'Host',
			name: 'host',
			type: 'string',
			default: 'localhost',
			description: 'Hostname or IP of the cctvQL server',
		},
		{
			displayName: 'Port',
			name: 'port',
			type: 'number',
			default: 8000,
		},
		{
			displayName: 'Protocol',
			name: 'protocol',
			type: 'options',
			options: [
				{ name: 'HTTP', value: 'http' },
				{ name: 'HTTPS', value: 'https' },
			],
			default: 'http',
		},
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			description: 'Optional API key (leave blank if authentication is disabled)',
		},
	];
}
