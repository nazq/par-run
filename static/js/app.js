document.addEventListener('DOMContentLoaded', function() {
    const wsUrl = `ws://${window.location.host}/ws`;
    let ws;

    // Load and display the command configurations on startup
    function loadConfig() {
        fetch('/get-commands-config')
            .then(response => response.json())
            .then(configGroups => {
                createConfigWidgets(configGroups);
            })
            .catch(error => console.error('Error loading configuration:', error));
    }

    function getOutputMessage(data) {
        const commandName = data.commandName;
        const output = data.output;
    
        if (output && typeof output === 'object' && 'ret_code' in output) {
            if (output.ret_code === 0) {
                return `<span class="text-success">&#10004;</span> Success`;
            } else {
                return `<span class="text-danger">&#10008;</span> Failed`;
            }
        } else if (output && typeof output === 'object') {
            // If output is an object but not a ret_code, stringify it
            return JSON.stringify(output);
        } else {
            return output; // Return the original output message
        }
    }
    
    
    

    // Dynamically create widgets for command configurations
    function createConfigWidgets(configGroups) {
        const container = document.getElementById('configGroups');
        container.innerHTML = '';  // Clear existing widgets

        configGroups.forEach(group => {
            const table = document.createElement('table');
            table.className = 'table';
            
            const thead = document.createElement('thead');
            thead.innerHTML = `<tr><th colspan="2">${group.name}</th></tr>`;
            table.appendChild(thead);

            const tbody = document.createElement('tbody');
            group.cmds.forEach(command => {
                const tr = document.createElement('tr');
                const tdName = document.createElement('td');
                tdName.textContent = command.name;
                const tdCmd = document.createElement('td');
                const inputCmd = document.createElement('input');
                inputCmd.type = 'text';
                inputCmd.className = 'form-control';
                inputCmd.value = command.cmd;
                inputCmd.dataset.commandName = command.name;
                tdCmd.appendChild(inputCmd);
                tr.appendChild(tdName);
                tr.appendChild(tdCmd);
                tbody.appendChild(tr);
            });
            table.appendChild(tbody);
            container.appendChild(table);
        });
    }

    function getCurrentConfig() {
        return Array.from(document.getElementsByClassName('table')).map(table => {
            const group = table.getElementsByTagName('th')[0].textContent;
            const cmds = Array.from(table.getElementsByTagName('input')).map(input => {
                return { name: input.dataset.commandName, cmd: input.value };
            });
            return { name: group, cmds };
        });
    }

    // Save the updated configurations
    document.getElementById('saveConfig').addEventListener('click', function() {
        console.log('Saving configurations...');
        const configGroups = getCurrentConfig();
    
        console.log(JSON.stringify(configGroups));
        fetch('/update-commands-config', {
            method: 'POST',
            body: JSON.stringify(configGroups),
            headers: { 'Content-Type': 'application/json' }
        });
    });

    // Initialize WebSocket connection and setup event listeners
    document.getElementById('executeCommands').addEventListener('click', function() {

        const runnerTabContent = new bootstrap.Tab(document.getElementById('runner-tab'));
        runnerTabContent.show();

        ws = new WebSocket(wsUrl);
        ws.addEventListener('open', function(event) {
            console.log('WebSocket Open', event);
        });
        ws.addEventListener('message', function(event) {
            console.log('WebSocket Message', event);
            const data = JSON.parse(event.data);
        
            // Handle regular output messages
            const commandName = data.commandName;
            const output = data.output;
        
            // Ensure the 'runnerOutputs' container exists
            const runnerOutputs = document.getElementById('runnerOutputs');
            if (!runnerOutputs) {
                console.error('Runner outputs container not found');
                return;
            }
        
            // Check if the section for this command already exists
            let commandSection = document.getElementById(`command-output-${commandName}`);
            if (!commandSection) {
                // Create a new collapsible section for this command
                commandSection = document.createElement('div');
                commandSection.id = `command-output-${commandName}`;
                commandSection.innerHTML = `
                    <button class="btn btn-block text-left mt-2" type="button" data-toggle="collapse" data-target="#collapse-${commandName}" aria-expanded="false" aria-controls="collapse-${commandName}">
                        <span style="color: blue; font-weight: bold;">${commandName}:</span> <span id="last-line-${commandName}">${getOutputMessage(data)}</span> <!-- Show last message in collapsed section header -->
                    </button>
                    <div id="collapse-${commandName}" class="collapse" aria-labelledby="heading-${commandName}">
                        <div class="card card-body custom-card card-body">
                            <!-- Command output will go here -->
                        </div>
                    </div>
                `;
                runnerOutputs.appendChild(commandSection);
            } else {
                // Update the last line in the section when collapsed
                const lastLine = document.querySelector(`#last-line-${commandName}`);
                if (lastLine) {
                    lastLine.innerHTML = getOutputMessage(data); // Update the last line content
                }
            }
        
            // Append the new output to the command's section
            const outputContainer = document.querySelector(`#collapse-${commandName} .card-body`);
            if (!outputContainer) {
                console.error(`Output container not found for command: ${commandName}`);
                return;
            }
        
            if (typeof data.output === 'object' && 'ret_code' in data.output) {
                // This is the final status message, skip updating the collapsed view
                return;
            }

            const p = document.createElement('p');
            p.textContent = output;
            outputContainer.appendChild(p);
            // Scroll to the bottom to show the latest output
            outputContainer.scrollTop = outputContainer.scrollHeight;
        
            // Scroll to the bottom if the section is collapsed
            const collapseSection = document.querySelector(`#collapse-${commandName}`);
            if (collapseSection.classList.contains('show')) {
                outputContainer.scrollTop = outputContainer.scrollHeight;
            } else {
                // Update the last line in the section when collapsed
                const button = document.querySelector(`#collapse-${commandName} button`);
                if (button) {
                    button.innerHTML = `${commandName}: ${getOutputMessage(data)}`; // Update section header with latest message
                }
            }
        });        
        ws.addEventListener('close', function(event) {
            console.log('WebSocket Closed', event);
        });
        ws.addEventListener('error', function(event) {
            console.error('WebSocket Error', event);
        });

        // Send a message to start the command execution
        //ws.send(JSON.stringify({action: 'start'}));
    });

    // Initial configuration load
    loadConfig();
});
