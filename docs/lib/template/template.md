% if el['header']:
${el['header']}
% else:
${el['doc']}
% endif
% if 'sig' in el.keys() and el['sig']:
`${el['sig']}`

[![Badge](https://img.shields.io/badge/SOURCE-black?style=plastic&logo=github)](https://github.com/wandb/client/tree/master/${source[2:]}#L${el['lineno'][0]}-#L${el['lineno'][1]})

    % if 'parse' in el.keys():
        % for segment in el['parse']:
**${segment['header']}**
    
${segment['text']}
    
            % if segment['args']:
| **Filed** | **Type** | **Description** |
|--|--|--|
                % for item in segment['args']:
| ${item['field']} | ${item['signature']} | ${item['description']} |
                % endfor
            % endif
        % endfor
    % endif
% endif